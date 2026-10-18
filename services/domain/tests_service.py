import logging

from sqlalchemy.exc import IntegrityError

from models.models import db, LabService, Laboratory
from services.shared.vector_service import upsert_test_vector, delete_test_vector
from services.shared.generation_service import regenerate_test, generate_test
from schemas.generation import TestGenerationResult

logger = logging.getLogger(__name__)


def _parse_tags(raw_list, fallback_str=None):
    """
    Parses and sanitizes list of tags/keywords/aliases from form data.
    Handles both multi-element lists and comma-separated string tokens.
    """
    tags = []
    if raw_list:
        for item in raw_list:
            if isinstance(item, str):
                for part in item.split(","):
                    p = part.strip()
                    if p and p not in tags:
                        tags.append(p)
            elif isinstance(item, (list, tuple)):
                for sub in item:
                    p = str(sub).strip()
                    if p and p not in tags:
                        tags.append(p)
    if not tags and fallback_str and isinstance(fallback_str, str):
        tags = [p.strip() for p in fallback_str.split(",") if p.strip()]
    return tags


class TestsService:
    # Initialize the tests service with optional test ID, LabService model, or laboratory ID
    def __init__(self, test_id=None, test=None, laboratory_id=None):
        """Init with a test_id, a pre-loaded LabService, or a laboratory_id. If `test` is given, test_id/laboratory_id are derived from it."""
        self.test_id = test_id
        self._test = test
        self.laboratory_id = laboratory_id
        if test:
            self.test_id = test.id
            if hasattr(test, 'laboratory_id') and test.laboratory_id is not None:
                self.laboratory_id = test.laboratory_id

    # Lazily fetch and return the cached LabService model instance
    @property
    def test(self):
        """Lazily load and cache the LabService for self.test_id."""
        if self._test is None and self.test_id is not None:
            self._test = db.session.get(LabService, self.test_id)
            if self._test and hasattr(self._test, 'laboratory_id') and self.laboratory_id is None:
                self.laboratory_id = self._test.laboratory_id
        return self._test

    # Retrieve a specific test service by ID or instance state
    def get_test(self, test_id=None):
        """Fetch a test by ID (or self.test_id), using the instance cache when it matches. Returns (LabService or None, message)."""
        target_id = test_id or self.test_id
        if not target_id and self._test:
            return self._test, "Test retrieved successfully"
        if not target_id:
            return None, "Test not found"

        if self._test and self._test.id == target_id:
            return self._test, "Test retrieved successfully"

        try:
            test = db.session.get(LabService, target_id)
            if test:
                if target_id == self.test_id or self.test_id is None:
                    self._test = test
                    self.test_id = test.id
                    if hasattr(test, 'laboratory_id') and self.laboratory_id is None:
                        self.laboratory_id = test.laboratory_id
                return test, "Test retrieved successfully"
            else:
                return None, "Test not found"
        except Exception as e:
            logger.exception("Failed to fetch test %s: %s", target_id, e)
            return None, "حدث خطأ أثناء جلب بيانات التحليل"

    # Backward-compatible alias to retrieve a test service by ID
    def get_test_by_id(self, test_id=None):
        """Backward-compatible alias for get_test()."""
        return self.get_test(test_id=test_id)


    # Retrieve paginated test services filtered by search term and laboratory ID
    def get_paginated_tests(self, page: int = 1, per_page: int = 10, search: str = None, laboratory_id: int = None):
        """Paginated LabService list, optionally filtered by name (ILIKE) and laboratory_id.
        Ordered ascending by id (id.asc()) — NOT descending, despite older docs; confirm if this should flip.
        """
        lab_id = laboratory_id or self.laboratory_id
        try:
            query = LabService.query
            if search and search.strip():
                search_term = f"%{search.strip()}%"
                query = query.filter(LabService.name.ilike(search_term))
            if lab_id:
                query = query.filter(LabService.laboratory_id == lab_id)

            pagination = query.order_by(LabService.id.asc()).paginate(
                page=page,
                per_page=per_page,
                error_out=False
            )
            return pagination, "Tests retrieved successfully"
        except Exception as e:
            logger.exception("Failed to paginate tests: %s", e)
            return None, "حدث خطأ أثناء جلب قائمة التحاليل"

    # Search laboratory test services for typeahead / autocomplete
    def search_services(self, query: str = "", limit: int = 15, laboratory_id: int = None):
        """Autocomplete search over name/aliases/keywords, ranked by match priority. Returns a list of dicts (id, name, price, patient_instructions), or [] on no query or error."""
        if not query or not query.strip():
            return []

        clean_query = query.strip()
        search_term = f"%{clean_query}%"
        lab_id = laboratory_id or self.laboratory_id

        try:
            from sqlalchemy import or_, cast, String, case

            query_filter = or_(
                LabService.name.ilike(search_term),
                cast(LabService.alias_name, String).ilike(search_term),
                cast(LabService.keywords, String).ilike(search_term),
            )

            stmt = LabService.query.filter(query_filter)
            if lab_id:
                stmt = stmt.filter(LabService.laboratory_id == lab_id)

            priority = case(
                (LabService.name.ilike(clean_query), 0),
                (LabService.name.ilike(f"{clean_query}%"), 1),
                (cast(LabService.alias_name, String).ilike(search_term), 2),
                else_=3
            )

            services = stmt.order_by(priority, LabService.name.asc()).limit(limit).all()

            return [
                {
                    "id": s.id,
                    "name": s.name,
                    "price": float(s.price or 0),
                    "patient_instructions": (s.patient_instructions[:80] + "...") if s.patient_instructions and len(s.patient_instructions) > 80 else (s.patient_instructions or "")
                }
                for s in services
            ]
        except Exception as e:
            logger.exception("search_services failed for query=%r: %s", clean_query, e)
            return []

    # Create and persist a new laboratory service and index its vector embedding
    def create_lab_service(self, laboratory_id: int = None, name: str = None, price: float = None, description: str = None,
                           patient_instructions: str = None, duration: int = None,
                           sample_type: str = None, keywords: list[str] = None,
                           alias_name: list[str] = None):
        """Create a LabService and index it in Qdrant. Duplicate names are rejected via a
        pre-check plus an IntegrityError catch (covers the race window between check and insert —
        requires a unique constraint on LabService.name). Returns (LabService or None, message).
        """
        lab_id = laboratory_id or self.laboratory_id
        try:
            name = name.strip() if name else ""
            if not name:
                return None, "اسم التحليل مطلوب"

            existing_test = LabService.query.filter_by(name=name).first()
            if existing_test:
                return None, "Test already exists"

            new_test = LabService(
                laboratory_id=lab_id,
                name=name,
                price=price,
                description=description,
                patient_instructions=patient_instructions,
                duration=duration,
                sample_type=sample_type,
                keywords=keywords,
                alias_name=alias_name
            )
            db.session.add(new_test)
            db.session.commit()
            self._test = new_test
            self.test_id = new_test.id
            self.laboratory_id = new_test.laboratory_id

            try:
                upsert_test_vector(new_test.id, new_test.name, new_test.description or "", new_test.keywords or [])
            except Exception as ve:
                logger.warning("Failed to upsert vector for test %s: %s", new_test.id, ve)

            return new_test, "Test created successfully"
        except IntegrityError as e:
            db.session.rollback()
            logger.warning("IntegrityError creating test name=%r: %s", name, e)
            return None, "Test already exists"
        except Exception as e:
            db.session.rollback()
            logger.exception("Failed to create test name=%r: %s", name, e)
            return None, "حدث خطأ أثناء إنشاء التحليل"

    # Update an existing test service and refresh its vector index
    def update_test(self, test_id: int = None, name: str = None, price: float = None, description: str = None,
                    instructions: str = None, duration: int = None, sample_type: str = None,
                    keywords: list[str] = None, alias_name: list[str] = None, laboratory_id: int = None):
        """Update the given non-None fields on a LabService and refresh its vector index.
        NOTE: passing laboratory_id moves the test to another lab — confirm this is intended.
        Returns (LabService or None, message); None means not found or the update failed.
        """
        target_id = test_id or self.test_id
        lab_id = laboratory_id or self.laboratory_id
        try:
            test = None
            if self._test and (not target_id or self._test.id == target_id):
                test = self._test
            elif target_id:
                test = db.session.get(LabService, target_id)

            if not test:
                return None, "Test not found"

            if lab_id is not None:
                test.laboratory_id = lab_id
            if name is not None:
                test.name = name
            if price is not None:
                test.price = price
            if description is not None:
                test.description = description
            if instructions is not None:
                test.patient_instructions = instructions
            if duration is not None:
                test.duration = duration
            if sample_type is not None:
                test.sample_type = sample_type
            if keywords is not None:
                test.keywords = keywords
            if alias_name is not None:
                test.alias_name = alias_name

            db.session.commit()
            self._test = test
            self.test_id = test.id
            self.laboratory_id = test.laboratory_id

            try:
                upsert_test_vector(test.id, test.name, test.description or "", test.keywords or [])
            except Exception as ve:
                logger.warning("Failed to upsert vector for test %s: %s", test.id, ve)

            return test, "Test updated successfully"
        except IntegrityError as e:
            db.session.rollback()
            logger.warning("IntegrityError updating test %s: %s", target_id, e)
            return None, "Test already exists"
        except Exception as e:
            db.session.rollback()
            logger.exception("Failed to update test %s: %s", target_id, e)
            return None, "حدث خطأ أثناء تحديث بيانات التحليل"

    # Delete a test service and remove its corresponding vector from Qdrant
    def delete_test(self, test_id: int = None):
        """Delete a test and remove its vector from Qdrant. Returns (deleted LabService or None, message)."""
        target_id = test_id or self.test_id
        try:
            test = None
            if self._test and (not target_id or self._test.id == target_id):
                test = self._test
            elif target_id:
                test = db.session.get(LabService, target_id)

            if not test:
                return None, "Test not found"

            test_id_copy = test.id
            db.session.delete(test)
            db.session.commit()
            self._test = None

            try:
                delete_test_vector(test_id_copy)
            except Exception as ve:
                logger.warning("Failed to delete vector for test %s: %s", test_id_copy, ve)

            return test, "Test deleted successfully"
        except Exception as e:
            db.session.rollback()
            logger.exception("Failed to delete test %s: %s", target_id, e)
            return None, "حدث خطأ أثناء حذف التحليل"

    # Retrieve all registered laboratories ordered alphabetically by name
    def get_all_laboratories(self):
        """All laboratories, ordered alphabetically by name."""
        from services.domain.laboratory_service import LaboratoryService
        return LaboratoryService.get_laboratories_ordered_by_name()

    # Compile pagination, services list, and laboratories for dashboard view rendering
    def get_test_service_page_data(self, page=1, per_page=10, search="", laboratory_id=None):
        """Bundle pagination + services + laboratories for the dashboard view. page/per_page are clamped (page>=1, 1<=per_page<=100)."""
        if page < 1:
            page = 1
        if per_page < 1 or per_page > 100:
            per_page = 10

        lab_id = laboratory_id or self.laboratory_id
        pagination, message = self.get_paginated_tests(
            page=page, per_page=per_page, search=search, laboratory_id=lab_id
        )

        services = pagination.items if pagination else []
        laboratories = self.get_all_laboratories()

        return pagination, services, laboratories, message

    # Validate and process submitted HTML form data to create a new test service
    def handle_create_test(self, form_data):
        """Validate form_data (name, laboratory_id, price required) and create a test. Returns (success, message) — message is user-facing Arabic."""
        try:
            name = form_data.get("name", "").strip()
            price = form_data.get("price")
            duration = form_data.get("duration")
            laboratory_id = form_data.get("laboratory_id") or self.laboratory_id

            if not name:
                return False, "اسم التحليل مطلوب"
            if not laboratory_id:
                return False, "يرجى اختيار المعمل"
            if not price:
                return False, "سعر التحليل مطلوب"

            keywords_raw = _parse_tags(
                form_data.getlist("keywords") or form_data.getlist("generated_keywords"),
                form_data.get("keywords")
            )
            alias_raw = _parse_tags(
                form_data.getlist("alias_name") or form_data.getlist("generated_aliases"),
                form_data.get("alias_name")
            )

            service, message = self.create_lab_service(
                laboratory_id=int(laboratory_id),
                name=name,
                price=float(price),
                duration=int(duration) if duration else None,
                patient_instructions=form_data.get("patient_instructions") or form_data.get("instructions"),
                description=form_data.get("description"),
                keywords=keywords_raw,
                alias_name=alias_raw,
                sample_type=form_data.get("sample_type"),
            )

            if not service:
                return False, message

            return True, "تم إضافة التحليل الطبي بنجاح"

        except ValueError:
            return False, "بيانات السعر أو المدة غير صحيحة"
        except Exception as e:
            logger.exception("handle_create_test failed: %s", e)
            return False, "حدث خطأ أثناء إضافة التحليل"

    # Validate and process submitted form data to update an existing test service
    def handle_update_test(self, form_data, test_id=None):
        """Validate form_data and update a test. Accepts (form_data, test_id) or the legacy
        inverted (test_id, form_data) call shape — auto-detected. Returns (success, message),
        propagating the real outcome of update_test() (previously this always reported success).
        """
        if isinstance(form_data, int) or (isinstance(test_id, dict) or hasattr(test_id, 'getlist')):
            actual_test_id, actual_form_data = form_data, test_id
        else:
            actual_test_id = test_id or self.test_id
            actual_form_data = form_data

        try:
            name = actual_form_data.get("name")
            price = actual_form_data.get("price")
            duration = actual_form_data.get("duration")
            laboratory_id = actual_form_data.get("laboratory_id") or self.laboratory_id

            keywords_raw = _parse_tags(
                actual_form_data.getlist("keywords") or actual_form_data.getlist("generated_keywords"),
                actual_form_data.get("keywords")
            )
            alias_raw = _parse_tags(
                actual_form_data.getlist("alias_name") or actual_form_data.getlist("generated_aliases"),
                actual_form_data.get("alias_name")
            )

            updated_test, message = self.update_test(
                test_id=actual_test_id,
                name=name.strip() if name else None,
                price=float(price) if price else None,
                duration=int(duration) if duration else None,
                instructions=actual_form_data.get("patient_instructions") or actual_form_data.get("instructions"),
                description=actual_form_data.get("description"),
                keywords=keywords_raw,
                alias_name=alias_raw,
                sample_type=actual_form_data.get("sample_type"),
                laboratory_id=int(laboratory_id) if laboratory_id else None,
            )

            if not updated_test:
                return False, message

            return True, "تم تحديث بيانات التحليل بنجاح"

        except ValueError:
            return False, "قيم السعر أو المدة غير صحيحة"
        except Exception as e:
            logger.exception("handle_update_test failed for test_id=%r: %s", actual_test_id, e)
            return False, "حدث خطأ أثناء تحديث التحليل"

    # Determine whether the incoming request expects JSON or was dispatched via AJAX
    def is_ajax_request(self, request):
        """True if the Flask request is JSON, XHR, or Accepts application/json."""
        return (
            request.is_json
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in request.headers.get("Accept", "")
        )

    # Trigger generative AI model to synthesize medical test description, instructions, and keywords
    def process_ai_generation(self, request):
        """Generate test metadata (description/instructions/keywords) from the request's name. Returns (TestGenerationResult or None, error or None)."""
        try:
            if request.is_json:
                data = request.get_json(silent=True) or {}
                name = data.get("name", "").strip()
                description = data.get("description")
                instructions = data.get("patient_instructions") or data.get("instructions")
            else:
                name = request.form.get("name", "").strip()
                description = request.form.get("description")
                instructions = request.form.get("patient_instructions") or request.form.get("instructions")

            if not name:
                return None, "اسم التحليل مطلوب"

            result = generate_test(name=name, description=description, instructions=instructions)
            return result, None
        except Exception as e:
            logger.exception("process_ai_generation failed: %s", e)
            return None, "حدث خطأ أثناء توليد بيانات التحليل بالذكاء الاصطناعي"

    # Trigger generative AI model to regenerate alternative metadata for a medical test
    def process_ai_regeneration(self, request):
        """Regenerate alternative test metadata given the previous AI output in the request. Returns (TestGenerationResult or None, error or None)."""
        try:
            if request.is_json:
                data = request.get_json(silent=True) or {}
                name = data.get("name", "").strip()
                prev_raw = data.get("previous_output") or {}
                previous_output = TestGenerationResult(
                    description=prev_raw.get("description", ""),
                    patient_instructions=prev_raw.get("instructions") or prev_raw.get("patient_instructions", ""),
                    keywords=prev_raw.get("keywords") or [],
                    alias_name=prev_raw.get("aliases") or prev_raw.get("alias_name") or [],
                )
            else:
                name = request.form.get("name", "").strip()
                previous_output = TestGenerationResult(
                    description=request.form.get("generated_description", ""),
                    patient_instructions=request.form.get("generated_instructions", ""),
                    keywords=request.form.getlist("generated_keywords"),
                    alias_name=request.form.getlist("generated_aliases"),
                )

            if not name:
                return None, "اسم التحليل مطلوب"

            result = regenerate_test(name=name, previous_output=previous_output)
            return result, None
        except Exception as e:
            logger.exception("process_ai_regeneration failed: %s", e)
            return None, "حدث خطأ أثناء إعادة توليد بيانات التحليل بالذكاء الاصطناعي"

    # Format AI TestGenerationResult schema object into a JSON-compatible dictionary
    def format_ai_response(self, result):
        """Map a TestGenerationResult to the dict shape the dashboard form expects (dual keys for instructions/aliases)."""
        return {
            "description": result.description,
            "instructions": result.patient_instructions,
            "patient_instructions": result.patient_instructions,
            "keywords": result.keywords,
            "aliases": result.alias_name,
            "alias_name": result.alias_name,
            "duration": result.duration,
            "sample_type": result.sample_type,
        }

    @staticmethod
    def get_services_by_ids(service_ids: list):
        """Fetch LabService instances by IDs."""
        if not service_ids:
            return []
        try:
            int_ids = [int(sid) for sid in service_ids if str(sid).isdigit()]
            if not int_ids:
                return []
            return LabService.query.filter(LabService.id.in_(int_ids)).all()
        except Exception as e:
            logger.exception("[TestsService.get_services_by_ids] Error: %s", e)
            return []

    @staticmethod
    def get_total_tests_count() -> int:
        """Fetch total count of lab services."""
        try:
            return LabService.query.count()
        except Exception:
            return 0