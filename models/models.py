from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from flask_login import UserMixin
from sqlalchemy import ForeignKeyConstraint, PrimaryKeyConstraint
from enum import Enum

db = SQLAlchemy()

# Enum status for bookings, complaints, and inquiries
class Status(Enum):
    PENDING = "Pending" 
    REVIEWED = "Reviewed" 
    ATTENDED = "Attended"
    NO_SHOW = "No Show"


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True) # Incremental ID for the user
    name = db.Column(db.String(100), nullable=False) # Name of the user
    password = db.Column(db.String(100), nullable=False) # Password of the user
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=True, index=True) # NULL = admin who sees every lab
    role = db.Column(db.String(20), nullable=False, default='lab_user') # 'admin' or 'lab_user'

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def username(self):
        return self.name

    @username.setter
    def username(self, value):
        self.name = value


class Laboratory(db.Model):
    __tablename__ = 'laboratories'
    id = db.Column(db.Integer, primary_key=True) # Incremental ID
    name = db.Column(db.String(100), nullable=False) # Name of the laboratory (used for agent prompt)
    location = db.Column(db.TEXT, nullable=False) # Location of the laboratory (used for agent prompt)
    description = db.Column(db.TEXT, nullable=True) # Description, work hours, or details (used for agent prompt)
    logo_path = db.Column(db.String(255), nullable=True) # Logo file path relative to /static (dashboard, ticket PDF)
    support_phone = db.Column(db.String(30), nullable=True) # Customer-service number shown to patients
    notification_email = db.Column(db.String(255), nullable=True) # Where this lab's booking/prescription alerts go (comma separated)
    billing_laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=True) # NULL = own subscription, else shares that lab's subscription

    # Relationships
    users = db.relationship('User', backref='laboratory', lazy=True)
    subscription = db.relationship('Subscription', backref='laboratory', uselist=False, lazy=True)
    lab_services = db.relationship('LabService', backref='laboratory', lazy=True)
    pages = db.relationship('Page', backref='laboratory', lazy=True)
    lab_inquiries = db.relationship('Inquiry', backref='laboratory', lazy=True)
    result_requests = db.relationship('ResultRequest', backref='laboratory', lazy=True)


# Compatibility alias
Lab = Laboratory


class LabService(db.Model):
    __tablename__ = 'lab_services'
    id = db.Column(db.Integer, primary_key=True) # Incremental ID
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False) # Foreign Key linking to Laboratory
    name = db.Column(db.String(100), nullable=False,unique=True) # Name of the service (used for agent prompt and search)
    price = db.Column(db.Float, nullable=False) # Price of the test (used for agent prompt)
    duration = db.Column(db.Integer) # AI generation field for agent prompt
    patient_instructions = db.Column(db.TEXT, nullable=True) # Instructions for the patient regarding the test (used for agent prompt)
    description = db.Column(db.TEXT, nullable=True) # Description of the test (used for agent prompt and RAG search)
    alias_name = db.Column(db.JSON, nullable=True) # List of alias names for the test (used for agent and search)
    keywords = db.Column(db.JSON, nullable=True) # List of keywords for the test (used for agent and search)
    sample_type = db.Column(db.String(100)) # Sample type required for the test (used for agent prompt)


class Platform(db.Model):
    __tablename__ = 'platforms'
    id = db.Column(db.Integer, primary_key=True) # Incremental ID for the platform
    name = db.Column(db.String(100), nullable=False) # Name of the platform (e.g., Facebook, WhatsApp)

    # Relationships
    pages = db.relationship('Page', backref='platform', lazy=True, cascade="all, delete-orphan")


# Composite primary key for page_id and platform_id
class Page(db.Model):
    __tablename__ = 'pages'
    __table_args__ = (
        PrimaryKeyConstraint('page_id', 'platform_id'),
    )
    page_id = db.Column(db.String(100), nullable=False) # Page ID used to identify the page (from Facebook Developer)
    token = db.Column(db.Text, nullable=False) # Access token for page permissions (from Facebook Developer)
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'), nullable=False) # Foreign Key linking to Platform
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False) # Foreign Key linking to Laboratory

    # Relationships
    clients = db.relationship('Client', backref='page', lazy=True, cascade="all, delete-orphan")


# Composite primary key for sender_id, page_id, and platform_id
class Client(db.Model):
    __tablename__ = 'clients'
    __table_args__ = (
        PrimaryKeyConstraint('sender_id', 'page_id', 'platform_id'),
        ForeignKeyConstraint(
            ['page_id', 'platform_id'],
            ['pages.page_id', 'pages.platform_id']
        ),
    )
    sender_id = db.Column(db.String(100), nullable=False) # Sender ID received from Facebook or WAHA request
    page_id = db.Column(db.String(100), nullable=False) # Foreign Key linking to Page
    platform_id = db.Column(db.Integer, nullable=False) # Foreign Key linking to Platform
    summary = db.Column(db.Text, nullable=True) # Chat summary (used for agent memory)
    last_bot_reply = db.Column(db.Text, nullable=True) # Last bot reply (used for agent memory)
    chat_history = db.Column(db.JSON, nullable=False, default=list) # Chat history containing the last 7 pairs of messages and timestamps (used for agent memory)


class Booking(db.Model):
    __tablename__ = 'bookings'
    id = db.Column(db.Integer, primary_key=True) # Incremental ID
    reference_id = db.Column(db.String(20), unique=True, nullable=True, index=True) # Unique reference ID for the booking
    name = db.Column(db.String(120), nullable=False) # Name of the client or patient
    details = db.Column(db.Text) # The tests the user wants to book
    date = db.Column(db.String(100)) # Date of the booking
    phone_number = db.Column(db.String(50)) # Phone number associated with the booking
    status = db.Column(db.Enum(Status), default=Status.PENDING) # Status of the booking (e.g., PENDING)
    booking_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Timestamp of when the booking was saved to DB
    time = db.Column(db.String(20), nullable=True) # Specific time requested by the user for the booking
    comes_from = db.Column(db.String(100)) # Source platform (e.g., WhatsApp, Facebook)
    address = db.Column(db.String(255), nullable=False) # Address of the user or patient
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False, index=True) # Lab that received the booking (from the page, never from the LLM)


class Inquiry(db.Model):
    __tablename__ = 'inquiries'
    id = db.Column(db.Integer, primary_key=True) # Incremental ID
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False) # Foreign Key linking to Laboratory
    prescription_img = db.Column(db.String(255), nullable=True) # Path/URL of the prescription image sent by the patient
    status = db.Column(db.Enum(Status), default=Status.PENDING) # Status of the inquiry
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Timestamp when saved to DB
    comes_from = db.Column(db.String(100)) # Source platform (e.g., WhatsApp, Facebook)
    phone_number = db.Column(db.String(20)) # Phone number of the sender
    ocr_extracted_text = db.Column(db.Text) # Text extracted from the image using OCR
    confidence_score = db.Column(db.Float) # OCR confidence score
    services_mentioned = db.Column(db.String(500)) # Services mentioned (used if the admin selects the tests manually during review)
    deleted_at = db.Column(db.DateTime, nullable=True) # Timestamp to track deletion of images older than 8 days
    deletion_reason = db.Column(db.String(50), nullable=True) # Reason for deletion


class Complaint(db.Model):
    __tablename__ = 'complaints'
    id = db.Column(db.Integer, primary_key=True) # Incremental ID for the complaint
    phone_number = db.Column(db.String(20), nullable=False) # Phone number of the user filing the complaint
    complaint_text = db.Column(db.Text, nullable=False) # The actual text content of the complaint
    status = db.Column(db.Enum(Status), default=Status.PENDING) # Status of the complaint (e.g., PENDING, REVIEWED)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Timestamp when the complaint was submitted
    comes_from = db.Column(db.String(100)) # Source platform where the complaint originated (e.g., WhatsApp, Facebook)
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False, index=True) # Lab that received the complaint (from the page, never from the LLM)


class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True) # Incremental ID for the subscription
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False, unique=True) # Foreign Key linking to the subscribed Laboratory
    plan_name = db.Column(db.String(100), default="Standard", nullable=False) # Name of the subscription plan (e.g., Standard, Premium)
    message_limit = db.Column(db.Integer, default=5000, nullable=False) # Maximum number of allowed messages per cycle
    message_used = db.Column(db.Integer, default=0, nullable=False) # Number of messages consumed so far
    grace_limit = db.Column(db.Integer, default=50, nullable=False) # Extra allowed messages beyond the limit before hard stop
    estimated_cost = db.Column(db.Float, default=0.0, nullable=False) # Estimated cost of the subscription plan
    start_date = db.Column(db.DateTime) # Subscription cycle start date
    end_date = db.Column(db.DateTime) # Subscription cycle end/expiry date
    renew_count = db.Column(db.Integer, default=0, nullable=False) # Number of times the subscription has been renewed
    last_renewed_at = db.Column(db.DateTime) # Timestamp of the most recent renewal
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Timestamp when the subscription was initially created
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)) # Timestamp of the last update
    is_active = db.Column(db.Boolean, default=True, nullable=False) # Boolean indicating if the subscription is currently active
    usage_alert_sent = db.Column(db.Boolean, default=False, nullable=False) # True once the 80% usage alert was emailed for this cycle (cleared on renew/reset)


class LabUsage(db.Model):
    __tablename__ = "lab_usage"
    __table_args__ = (
        db.UniqueConstraint('laboratory_id', 'usage_date', name='uq_lab_usage_lab_date'),
    )
    id = db.Column(db.Integer, primary_key=True)
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=False, index=True) # Lab that consumed the units
    usage_date = db.Column(db.Date, nullable=False) # Day of consumption
    units = db.Column(db.Integer, default=0, nullable=False) # Units consumed that day (text=1, image=2)
    cost = db.Column(db.Float, default=0.0, nullable=False) # Estimated cost that day


class Feedback(db.Model):
    __tablename__ = "feedbacks"
    id = db.Column(db.Integer, primary_key=True) # Incremental ID for the feedback entry
    reference_id = db.Column(db.String(50), nullable=False) # Reference ID linking feedback to a specific booking or interaction
    name = db.Column(db.String(50), nullable=False) # Name of the person leaving the feedback
    phone_number = db.Column(db.String(50), nullable=False) # Phone number of the person leaving the feedback
    overall_rating = db.Column(db.Integer, nullable=False) # Overall rating score (e.g., 1 to 5)
    ease_of_use = db.Column(db.Integer, nullable=False) # Rating specifically for ease of use
    feedback_text = db.Column(db.Text, nullable=True) # Optional text provided by the user for additional comments
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc)) # Timestamp when the feedback was submitted



class TenantSettings(db.Model):
    __tablename__ = "tenant_settings"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(50), unique=True, nullable=False)
    
    # 1. الإيميل اللي العميل عايز يستلم عليه الرسائل
    notification_email = db.Column(db.String(255), nullable=True)
    
    # 2. نص الـ Token الخاص بـ Gmail اللي هيرجع من Google
    gmail_token_json = db.Column(db.Text, nullable=True)   

class Bundle(db.Model):
    __tablename__ ="bundle"

    id = db.Column(db.Integer,primary_key=True)  
    name=db.Column(db.String(50),unique=True,nullable=True)
    price = db.Column(db.Float, nullable=False)
    description=db.Column(db.Text())  
    instructions = db.Column(db.Text())


class ResultRequest(db.Model):
    __tablename__ = 'result_requests'
    id = db.Column(db.Integer, primary_key=True)
    user_identity = db.Column(db.String(150), nullable=False, index=True)  # WhatsApp phone OR Facebook name
    laboratory_id = db.Column(db.Integer, db.ForeignKey('laboratories.id'), nullable=True)
    status = db.Column(db.Enum(Status), default=Status.PENDING)  # PENDING / REVIEWED
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
