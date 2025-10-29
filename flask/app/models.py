from app import db, login_manager
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from time import time
import jwt
from app import app
from sqlalchemy.dialects.mysql import LONGTEXT, VARCHAR


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(user_id)
    return user


# Team membership association table
team_membership = db.Table('team_membership',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('team_id', db.Integer, db.ForeignKey('teams.id'), primary_key=True)
)


class User(db.Model, UserMixin):

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), default="")
    email = db.Column(db.String(255), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    courses = db.relationship(
        "Course", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def is_super_admin(self):
        super_admins = app.config.get('SUPER_ADMINS', [])
        return self.email in super_admins

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            if key == "password":
                value = generate_password_hash(value)
            setattr(self, key, value)

    def check_password(self, password):
        try:
            return check_password_hash(self.password_hash, password)
        except:
            return False

    def set_password(self, password2hash):
        self.password_hash = generate_password_hash(password2hash)

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {"reset_password": self.id, "exp": time() + expires_in},
            app.config["SECRET_KEY"],
            algorithm="HS256",
        )

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])[
                "reset_password"
            ]
        except:
            return
        return User.query.get(id)

    def __repr__(self):
        return f"User {self.email}"


class Event(db.Model):

    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.String(255), default="", index=True)
    type_name = db.Column(db.String(255))
    intent_name = db.Column(db.String(255), default="")
    action_name = db.Column(db.String(255), default="")
    timestamp = db.Column(db.Float)
    data = db.Column(LONGTEXT)

    __table_args__ = (
        db.Index("ix_events_sender_id_type_name_timestamp", "sender_id", "type_name", "timestamp"),
        db.Index("ix_events_timestamp", "timestamp"),
        db.Index("ix_events_data_sender_id", "data", "sender_id", mysql_prefix='FULLTEXT'),
    )


class Lecture(db.Model):

    __tablename__ = "lectures"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    description = db.Column(LONGTEXT)
    steps = db.relationship(
        "Step", backref="step", lazy=True, cascade="all, delete-orphan"
    )
    last_edited = db.Column(db.DateTime)
    position = db.Column(db.Integer, default=0, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)

    def copy(self):
        new = Lecture()
        new.name = self.name
        new.description = self.description
        for step in self.steps:
            new.steps.append(step.copy())
        new.last_edited = self.last_edited
        new.position = self.position
        return new


class Course(db.Model):

    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    description = db.Column(LONGTEXT)
    lectures = db.relationship(
        "Lecture", backref="lecture", lazy=True, cascade="all, delete-orphan"
    )
    company_id = db.Column(db.Integer, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def copy(self):
        new = Course()
        new.name = self.name
        new.description = self.description
        for lecture in self.lectures:
            print(lecture, flush=True)
            new.lectures.append(lecture.copy())
        return new


class Step(db.Model):

    __tablename__ = "lectures_steps"

    id = db.Column(db.Integer, primary_key=True)
    step_type = db.Column(db.String(255))
    free_input = db.Column(db.Boolean, default=False)
    response_type = db.Column(db.String(255))
    description = db.Column(LONGTEXT)
    text = db.Column(LONGTEXT)
    text2 = db.Column(LONGTEXT)
    text3 = db.Column(LONGTEXT, default="")
    parent_id = db.Column(db.Integer)
    lecture_id = db.Column(db.Integer, db.ForeignKey("lectures.id"), nullable=False)
    answers = db.relationship(
        "Answer", backref="answer", lazy=True, cascade="all, delete-orphan"
    )
    position = db.Column(db.Integer, default=0, nullable=False)

    def copy(self):
        new = Step()
        new.step_type = self.step_type
        new.free_input = self.free_input
        new.response_type = self.response_type
        new.description = self.description
        new.text = self.text
        new.text2 = self.text2
        new.text3 = self.text3
        new.parent_id = self.parent_id
        new.lecture_id = self.lecture_id
        new.position = self.position
        for answer in self.answers:
            new.answers.append(answer.copy())
        return new


class Answer(db.Model):

    __tablename__ = "lectures_answers"

    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, db.ForeignKey("lectures_steps.id"))
    text2match = db.Column(LONGTEXT)
    description = db.Column(LONGTEXT)
    answer_type = db.Column(db.String(255))
    text = db.Column(LONGTEXT)
    text2 = db.Column(LONGTEXT)
    parent_id = db.Column(db.Integer)
    correct_answer = db.Column(db.Boolean, default=False)
    following_action = db.Column(db.String(255), default="")
    following_action_id = db.Column(db.String(255), default="")
    position = db.Column(db.Integer, default=0, nullable=False)

    def copy(self):
        new = Answer()
        new.step_id = self.step_id
        new.text2match = self.text2match
        new.description = self.description
        new.answer_type = self.answer_type
        new.text = self.text
        new.text2 = self.text2
        new.parent_id = self.parent_id
        new.correct_answer = self.correct_answer
        new.following_action = self.following_action
        new.following_action_id = self.following_action_id
        new.position = self.position
        return new


class EventsSlot(db.Model):

    __tablename__ = "events_slots"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.String(255), default="")
    key2find = db.Column(db.String(255), default="")
    value = db.Column(db.Text(), default="")

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class PlannedTask(db.Model):

    __tablename__ = "planned_tasks"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(255))
    sender_id = db.Column(db.String(255))
    eta = db.Column(db.DateTime)
    is_finished = db.Column(db.Boolean, default=0)

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


# New models - After adding these models, create an Alembic migration with:
# flask db migrate -m "Add ChatSession and FlaggedResponse models"
# flask db upgrade


class ChatSession(db.Model):

    __tablename__ = "chat_sessions"

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role_id = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Relationship
    user = db.relationship("User", backref=db.backref("chat_sessions", lazy=True))
    flagged_responses = db.relationship("FlaggedResponse", backref="session", lazy=True, cascade="all, delete-orphan")
    chat_messages = db.relationship("ChatMessage", backref="session", lazy=True, cascade="all, delete-orphan")
    
    def __init__(self, **kwargs):
        # Generate a simple random ID instead of UUID
        import random
        import time
        self.id = f"{int(time.time())}-{random.randint(10000, 99999)}"
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __repr__(self):
        return f"ChatSession {self.id}"


class FlaggedResponse(db.Model):

    __tablename__ = "flagged_responses"

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)
    session_id = db.Column(db.String(36), db.ForeignKey("chat_sessions.id"), nullable=False)
    content = db.Column(LONGTEXT) # The actual message content that was flagged
    message_index = db.Column(db.Integer, nullable=True)  # Index of the message in the chat history
    summary = db.Column(db.Text(), nullable=True)  # New field for the flag summary
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    is_public = db.Column(db.Boolean, default=False)  # Controls visibility to other users
    
    # Relationships
    user = db.relationship("User", backref=db.backref("flagged_responses", lazy=True))
    
    def __init__(self, **kwargs):
        # Generate a simple random ID instead of UUID
        import random
        import time
        self.id = f"{int(time.time())}-{random.randint(10000, 99999)}"
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __repr__(self):
        return f"FlaggedResponse {self.id}"


class ChatMessage(db.Model):
    """Model for storing individual chat messages for long-term persistence."""
    
    __tablename__ = "chat_messages"
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), db.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # 'system', 'user', or 'assistant'
    content = db.Column(db.Text(), nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    message_index = db.Column(db.Integer, nullable=False)  # To maintain message order
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __repr__(self):
        return f"<ChatMessage {self.id}: {self.role[:10]}>"


class Team(db.Model):
    """Team model for grouping users in a competition context."""

    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(VARCHAR(100), unique=True, nullable=False)
    description = db.Column(db.Text())
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Relationships
    members = db.relationship(
        "User", 
        secondary=team_membership,
        backref=db.backref("teams", lazy=True),
        lazy="dynamic"
    )
    flagged_responses = db.relationship("FlaggedResponse", backref="team", lazy=True)
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __repr__(self):
        return f"Team {self.name}"
