from flask import Blueprint, request, render_template, redirect, url_for, flash, jsonify
from flask_login import login_required
from services.domain.tests_service import TestsService

test_bp = Blueprint("test", __name__)


@test_bp.route("/test_service", methods=["GET"])
@login_required
def test_service():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    search = request.args.get("search", "").strip()
    laboratory_id = request.args.get("laboratory_id", type=int)

    tests_service = TestsService(laboratory_id=laboratory_id)
    pagination, services, laboratories, message = tests_service.get_test_service_page_data(
        page=page, per_page=per_page, search=search
    )

    if pagination is None and message:
        flash(message, "error")

    return render_template(
        "test/test_service.html",
        services=services,
        pagination=pagination,
        search=search,
        page=page,
        per_page=per_page,
        laboratory_id=laboratory_id,
        laboratories=laboratories
    )


@test_bp.route("/tests/search", methods=["GET"])
@test_bp.route("/api/tests/search", methods=["GET"])
@login_required
def search_tests():
    query = request.args.get("q", "").strip()
    limit = min(request.args.get("limit", 15, type=int), 30)
    laboratory_id = request.args.get("laboratory_id", type=int)

    tests_service = TestsService(laboratory_id=laboratory_id)
    results = tests_service.search_services(query=query, limit=limit)
    return jsonify(results)


@test_bp.route("/tests/create", methods=["GET", "POST"])
@login_required
def create_test():
    tests_service = TestsService()
    if request.method == "GET":
        laboratories = tests_service.get_all_laboratories()
        return render_template("test/test_form.html", laboratories=laboratories, is_edit=False)

    success, message = tests_service.handle_create_test(request.form)
    flash(message, "success" if success else "error")
    
    if success:
        return redirect(url_for("test.test_service"))
    return redirect(url_for("test.create_test"))


@test_bp.route("/tests/<int:test_id>/edit", methods=["GET", "POST"])
@login_required
def edit_test(test_id):
    tests_service = TestsService(test_id=test_id)
    service, message = tests_service.get_test()
    laboratories = tests_service.get_all_laboratories()

    if not service:
        flash(message, "error")
        return redirect(url_for("test.test_service"))

    if request.method == "GET":
        return render_template(
            "test/test_form.html",
            service=service,
            laboratories=laboratories,
            is_edit=True
        )

    success, message = tests_service.handle_update_test(request.form)
    flash(message, "success" if success else "error")

    if success:
        return redirect(url_for("test.test_service"))
    return redirect(url_for("test.edit_test", test_id=test_id))


@test_bp.route("/tests/<int:test_id>/delete", methods=["POST"])
@login_required
def delete_test(test_id):
    tests_service = TestsService(test_id=test_id)
    service, message = tests_service.delete_test()
    flash(message, "success" if service else "error")
    return redirect(url_for("test.test_service"))


@test_bp.route("/tests/generate", methods=["POST"])
@login_required
def generate():
    tests_service = TestsService()
    is_ajax = tests_service.is_ajax_request(request)
    result, error_msg = tests_service.process_ai_generation(request)

    if error_msg:
        if is_ajax:
            return jsonify({"error": error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for("test.create_test"))

    if is_ajax:
        return jsonify(tests_service.format_ai_response(result))

    laboratories = tests_service.get_all_laboratories()
    return render_template(
        "test/test_form.html",
        generated=result,
        form_data=request.form,
        laboratories=laboratories,
        is_edit=False
    )


@test_bp.route("/tests/regenerate", methods=["POST"])
@login_required
def regenerate():
    tests_service = TestsService()
    is_ajax = tests_service.is_ajax_request(request)
    result, error_msg = tests_service.process_ai_regeneration(request)

    if error_msg:
        if is_ajax:
            return jsonify({"error": error_msg}), 400
        flash(error_msg, "error")
        return redirect(url_for("test.create_test"))

    if is_ajax:
        return jsonify(tests_service.format_ai_response(result))

    laboratories = tests_service.get_all_laboratories()
    return render_template(
        "test/test_form.html",
        generated=result,
        form_data=request.form,
        laboratories=laboratories,
        is_edit=False
    )