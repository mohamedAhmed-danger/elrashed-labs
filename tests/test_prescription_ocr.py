import unittest
from unittest.mock import MagicMock, patch

from services.messaging.ocr_service import TestItem, PrescriptionOCRResult
from services.messaging.prescription_intake import extract_prescription_payload
from models.models import Status


class TestPrescriptionOCRFlow(unittest.TestCase):

    def setUp(self):
        self.dummy_message = MagicMock()
        self.dummy_message.sender_id = "user_123"
        self.dummy_message.platform_name = "facebook"
        self.dummy_message.platform_id = 1
        self.dummy_message.page_id = "page_456"
        self.dummy_message.text = "صورة روشتة"

        self.dummy_page = MagicMock()
        self.dummy_page.laboratory_id = 10

        self.sample_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xd9"

    @patch("services.messaging.prescription_intake.InquiryService")
    @patch("services.messaging.prescription_intake.ClientService")
    @patch("services.messaging.prescription_intake.consume_subscription")
    @patch("services.messaging.prescription_intake.analyze_prescription_image")
    def test_classification_spam_not_prescription(
        self, mock_ocr, mock_consume, mock_client_service, mock_inquiry_service
    ):
        """Step A: If is_prescription is False, do NOT create Inquiry, return spam label to agent."""
        mock_ocr.return_value = (
            PrescriptionOCRResult(
                is_prescription=False,
                extracted_text="Some random text or receipt",
                tests=[],
            ),
            {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )

        result = extract_prescription_payload(
            self.sample_bytes, self.dummy_message, self.dummy_page
        )

        self.assertEqual(result["mode"], "agent")
        self.assertEqual(result["text"], "[Image classified as spam or not a valid prescription]")
        mock_inquiry_service.assert_not_called()
        mock_consume.assert_called_once()
        mock_client_service.return_value.save_chat_exchange.assert_not_called()

    @patch("services.messaging.prescription_intake.InquiryService")
    @patch("services.messaging.prescription_intake.ClientService")
    @patch("services.messaging.prescription_intake.consume_subscription")
    @patch("services.messaging.prescription_intake.analyze_prescription_image")
    def test_prescription_low_confidence_any_test_below_70(
        self, mock_ocr, mock_consume, mock_client_service, mock_inquiry_service
    ):
        """Step B: If is_prescription is True but ANY test has confidence < 0.70 -> PENDING."""
        mock_ocr.return_value = (
            PrescriptionOCRResult(
                is_prescription=True,
                extracted_text="CBC, Ferritin, TSH",
                tests=[
                    TestItem(name="CBC", confidence=0.95),
                    TestItem(name="Ferritin", confidence=0.82),
                    TestItem(name="TSH", confidence=0.55),  # < 0.70!
                ],
            ),
            {"input_tokens": 500, "output_tokens": 50, "total_tokens": 550},
        )

        mock_inquiry_instance = MagicMock()
        mock_inquiry_service.return_value.save_inquiry.return_value = MagicMock(
            inquiry=mock_inquiry_instance
        )

        result = extract_prescription_payload(
            self.sample_bytes, self.dummy_message, self.dummy_page
        )

        self.assertEqual(result["mode"], "agent")
        self.assertIn("Low OCR confidence (0.55)", result["text"])

        # Check Inquiry status was PENDING
        mock_inquiry_service.return_value.save_inquiry.assert_called_once()
        call_kwargs = mock_inquiry_service.return_value.save_inquiry.call_args.kwargs
        self.assertEqual(call_kwargs["status"], Status.PENDING)
        self.assertEqual(call_kwargs["confidence_score"], 0.55)
        self.assertIn("CBC", call_kwargs["services_mentioned"])

        mock_consume.assert_called_once()
        mock_client_service.return_value.save_chat_exchange.assert_not_called()

    @patch("services.messaging.prescription_intake.InquiryService")
    @patch("services.messaging.prescription_intake.ClientService")
    @patch("services.messaging.prescription_intake.consume_subscription")
    @patch("services.messaging.prescription_intake.analyze_prescription_image")
    def test_prescription_high_confidence_all_tests_above_70(
        self, mock_ocr, mock_consume, mock_client_service, mock_inquiry_service
    ):
        """Step C: If ALL tests have confidence >= 0.70 -> REVIEWED -> Agent routing."""
        mock_ocr.return_value = (
            PrescriptionOCRResult(
                is_prescription=True,
                extracted_text="CBC, Lipid Profile",
                tests=[
                    TestItem(name="CBC", confidence=0.95),
                    TestItem(name="Lipid Profile", confidence=0.75),
                ],
            ),
            {"input_tokens": 400, "output_tokens": 40, "total_tokens": 440},
        )

        mock_inquiry_instance = MagicMock()
        mock_inquiry_service.return_value.save_inquiry.return_value = MagicMock(
            inquiry=mock_inquiry_instance
        )

        result = extract_prescription_payload(
            self.sample_bytes, self.dummy_message, self.dummy_page
        )

        self.assertEqual(result["mode"], "agent")
        self.assertIn("[Prescription OCR Extracted Tests]: CBC, Lipid Profile", result["text"])
        self.assertEqual(result["ocr_usage"]["total_tokens"], 440)

        # Check Inquiry status was REVIEWED
        mock_inquiry_service.return_value.save_inquiry.assert_called_once()
        call_kwargs = mock_inquiry_service.return_value.save_inquiry.call_args.kwargs
        self.assertEqual(call_kwargs["status"], Status.REVIEWED)
        self.assertEqual(call_kwargs["confidence_score"], 0.75)

        # Immediate 2-unit consumption occurs for all images after OCR
        mock_consume.assert_called_once()

    @patch("services.messaging.prescription_intake.InquiryService")
    @patch("services.messaging.prescription_intake.ClientService")
    @patch("services.messaging.prescription_intake.consume_subscription")
    @patch("services.messaging.prescription_intake.analyze_prescription_image")
    def test_prescription_empty_tests_safely_pending(
        self, mock_ocr, mock_consume, mock_client_service, mock_inquiry_service
    ):
        """Edge Case: Prescription with empty tests safely routes to PENDING doctor review."""
        mock_ocr.return_value = (
            PrescriptionOCRResult(
                is_prescription=True,
                extracted_text="Dr. Ahmed clinic - unreadable tests",
                tests=[],
            ),
            {"input_tokens": 300, "output_tokens": 30, "total_tokens": 330},
        )

        result = extract_prescription_payload(
            self.sample_bytes, self.dummy_message, self.dummy_page
        )

        self.assertEqual(result["mode"], "agent")
        self.assertIn("Low OCR confidence (0.00)", result["text"])

        mock_inquiry_service.return_value.save_inquiry.assert_called_once()
        call_kwargs = mock_inquiry_service.return_value.save_inquiry.call_args.kwargs
        self.assertEqual(call_kwargs["status"], Status.PENDING)

    @patch("services.messaging.prescription_intake.send_production_alert")
    @patch("services.messaging.prescription_intake.analyze_prescription_image")
    def test_technical_exception_triggers_alert_and_safe_reply(
        self, mock_ocr, mock_alert
    ):
        """Technical error (e.g. Gemini failure) triggers production alert and returns fallback."""
        mock_ocr.side_effect = RuntimeError("Gemini API network timeout")

        result = extract_prescription_payload(
            self.sample_bytes, self.dummy_message, self.dummy_page
        )

        self.assertEqual(result["mode"], "immediate")
        self.assertIn("حدث خطأ أثناء معالجة الصورة", result["reply"])
        mock_alert.assert_called_once()


class TestLayer1OCRService(unittest.TestCase):

    def test_pydantic_schema_validation(self):
        """Test strict validation of TestItem and PrescriptionOCRResult."""
        from pydantic import ValidationError

        item = TestItem(name="CBC", confidence=0.95)
        self.assertEqual(item.name, "CBC")
        self.assertEqual(item.confidence, 0.95)

        # Out of bounds confidence should raise ValidationError
        with self.assertRaises(ValidationError):
            TestItem(name="Bad", confidence=1.5)

        with self.assertRaises(ValidationError):
            TestItem(name="Bad", confidence=-0.1)

        result = PrescriptionOCRResult(
            is_prescription=True,
            extracted_text="CBC Ferritin TSH",
            tests=[
                TestItem(name="CBC", confidence=0.95),
                TestItem(name="Ferritin", confidence=0.82),
                TestItem(name="TSH", confidence=0.55),
            ],
        )
        self.assertTrue(result.is_prescription)
        self.assertEqual(len(result.tests), 3)

    def test_mime_type_detection(self):
        """Test detection of JPEG, PNG, WEBP."""
        from services.messaging.ocr_service import _detect_mime_type

        self.assertEqual(_detect_mime_type(b"\xff\xd8\xff\xe0..."), "image/jpeg")
        self.assertEqual(_detect_mime_type(b"\x89PNG\r\n\x1a\n..."), "image/png")
        self.assertEqual(_detect_mime_type(b"RIFF....WEBP...."), "image/webp")

    def test_empty_image_raises_value_error(self):
        """Passing empty bytes to analyze_prescription_image must raise ValueError."""
        from services.messaging.ocr_service import analyze_prescription_image

        with self.assertRaises(ValueError):
            analyze_prescription_image(b"")

    def test_missing_file_raises_file_not_found(self):
        """Passing a non-existent file path must raise FileNotFoundError."""
        from services.messaging.ocr_service import analyze_prescription_image

        with self.assertRaises(FileNotFoundError):
            analyze_prescription_image("non_existent_file_12345.jpg")


if __name__ == "__main__":
    unittest.main()
