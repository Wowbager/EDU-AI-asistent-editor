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
    db.Column('team_id', db.Integer, db.ForeignKey('teams.id'), primary_key=True),
    db.Index('ix_team_membership_team_id_user_id', 'team_id', 'user_id')
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
    position = db.Column(db.Integer, default=0, nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True, index=True)

    __table_args__ = (
        db.Index("ix_lectures_course_position", "course_id", "position"),
    )

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
    parent_id = db.Column(db.Integer, index=True)
    lecture_id = db.Column(db.Integer, db.ForeignKey("lectures.id"), nullable=False, index=True)
    answers = db.relationship(
        "Answer", backref="answer", lazy=True, cascade="all, delete-orphan"
    )
    position = db.Column(db.Integer, default=0, nullable=False, index=True)

    __table_args__ = (
        db.Index("ix_steps_lecture_parent", "lecture_id", "parent_id"),
        db.Index("ix_steps_lecture_position", "lecture_id", "position"),
    )

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
    step_id = db.Column(db.Integer, db.ForeignKey("lectures_steps.id"), index=True)
    text2match = db.Column(LONGTEXT)
    description = db.Column(LONGTEXT)
    answer_type = db.Column(db.String(255))
    text = db.Column(LONGTEXT)
    text2 = db.Column(LONGTEXT)
    parent_id = db.Column(db.Integer, index=True)
    correct_answer = db.Column(db.Boolean, default=False)
    following_action = db.Column(db.String(255), default="")
    following_action_id = db.Column(db.String(255), default="")
    position = db.Column(db.Integer, default=0, nullable=False, index=True)

    __table_args__ = (
        db.Index("ix_answers_step_position", "step_id", "position"),
    )

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
    sender_id = db.Column(db.String(255), default="", index=True)
    key2find = db.Column(db.String(255), default="")
    value = db.Column(db.Text(), default="")

    __table_args__ = (
        db.Index("ix_events_slots_sender_key", "sender_id", "key2find"),
        db.UniqueConstraint("sender_id", "key2find", name="uk_sender_key"),
    )

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class PlannedTask(db.Model):

    __tablename__ = "planned_tasks"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(255), index=True)
    sender_id = db.Column(db.String(255), index=True)
    eta = db.Column(db.DateTime)
    is_finished = db.Column(db.Boolean, default=0, index=True)

    __table_args__ = (
        db.Index("ix_planned_tasks_sender_finished", "sender_id", "is_finished"),
    )

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
    role_title = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        db.Index('ix_chat_sessions_user_created_id', 'user_id', 'created_at', 'id'),
    )
    
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

    __table_args__ = (
        db.Index('ix_flagged_responses_user_session', 'user_id', 'session_id'),
        db.Index('ix_flagged_responses_public_timestamp_session', 'is_public', 'timestamp', 'session_id'),
        db.Index('ix_flagged_responses_team_id', 'team_id'),
    )
    
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

    __table_args__ = (
        db.Index('ix_chat_messages_session_message_index', 'session_id', 'message_index'),
    )
    
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
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Relationships
    members = db.relationship(
        "User", 
        secondary=team_membership,
        backref=db.backref("teams", lazy=True),
        lazy="dynamic"
    )
    flagged_responses = db.relationship("FlaggedResponse", backref="team", lazy=True)
    invitations = db.relationship("TeamInvitation", backref="team", lazy=True, cascade="all, delete-orphan")
    creator = db.relationship("User", foreign_keys=[creator_id], backref="created_teams")
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __repr__(self):
        return f"Team {self.name}"


class TeamInvitation(db.Model):
    """Model for tracking team invitations."""

    __tablename__ = "team_invitations"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    inviter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    invitee_email = db.Column(db.String(255), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending, accepted, declined
    message = db.Column(db.Text(), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    responded_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_team_invitations_team_status_created_at', 'team_id', 'status', 'created_at'),
        db.Index('ix_team_invitations_invitee_status_created_at', 'invitee_email', 'status', 'created_at'),
        db.Index('ix_team_invitations_team_invitee_created_at', 'team_id', 'invitee_email', 'created_at'),
        db.Index('ix_team_invitations_inviter_created_at', 'inviter_id', 'created_at'),
    )
    
    # Relationships
    inviter = db.relationship("User", foreign_keys=[inviter_id], backref="sent_invitations")
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __repr__(self):
        return f"TeamInvitation(team_id={self.team_id}, invitee={self.invitee_email}, status={self.status})"
