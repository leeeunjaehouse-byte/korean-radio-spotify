from datetime import datetime
from cryptography.fernet import Fernet
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()


class User(db.Model):
    """User model for storing Spotify user information and tokens"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    spotify_user_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    profile_image_url = db.Column(db.String(500))

    # Encrypted tokens
    encrypted_access_token = db.Column(db.Text, nullable=False, default='')
    encrypted_refresh_token = db.Column(db.Text)
    token_expires_at = db.Column(db.DateTime)

    # User management
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    user_programs = db.relationship('UserProgram', back_populates='user', cascade='all, delete-orphan')
    user_playlists = db.relationship('UserPlaylist', back_populates='user', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.display_name} ({self.spotify_user_id})>'

    def set_access_token(self, access_token):
        """Encrypt and store access token"""
        self.encrypted_access_token = self._encrypt_token(access_token)

    def get_access_token(self):
        """Decrypt and retrieve access token"""
        return self._decrypt_token(self.encrypted_access_token)

    def set_refresh_token(self, refresh_token):
        """Encrypt and store refresh token"""
        if refresh_token:
            self.encrypted_refresh_token = self._encrypt_token(refresh_token)

    def get_refresh_token(self):
        """Decrypt and retrieve refresh token"""
        if self.encrypted_refresh_token:
            return self._decrypt_token(self.encrypted_refresh_token)
        return None

    @staticmethod
    def _encrypt_token(token):
        """Encrypt token using Fernet"""
        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            raise ValueError('ENCRYPTION_KEY environment variable not set')
        cipher = Fernet(key.encode() if isinstance(key, str) else key)
        return cipher.encrypt(token.encode()).decode()

    @staticmethod
    def _decrypt_token(encrypted_token):
        """Decrypt token using Fernet"""
        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            raise ValueError('ENCRYPTION_KEY environment variable not set')
        cipher = Fernet(key.encode() if isinstance(key, str) else key)
        return cipher.decrypt(encrypted_token.encode()).decode()


class UserProgram(db.Model):
    """Model for tracking which radio programs a user follows"""
    __tablename__ = 'user_programs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    program_code = db.Column(db.String(100), nullable=False)
    followed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    user = db.relationship('User', back_populates='user_programs')

    # Composite unique constraint
    __table_args__ = (
        db.UniqueConstraint('user_id', 'program_code', name='unique_user_program'),
    )

    def __repr__(self):
        return f'<UserProgram user_id={self.user_id} program_code={self.program_code}>'


class UserPlaylist(db.Model):
    """Model for storing generated Spotify playlists from radio programs"""
    __tablename__ = 'user_playlists'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    program_code = db.Column(db.String(100), nullable=False)
    created_date = db.Column(db.Date, nullable=False)

    # Spotify playlist information
    spotify_playlist_id = db.Column(db.String(255), nullable=False)
    spotify_playlist_url = db.Column(db.String(500), nullable=False)
    playlist_name = db.Column(db.String(255), nullable=False)

    # Playlist statistics
    total_songs = db.Column(db.Integer, default=0)
    songs_added = db.Column(db.Integer, default=0)
    songs_not_found = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = db.relationship('User', back_populates='user_playlists')

    # Composite unique constraint - one playlist per user per program per date
    __table_args__ = (
        db.UniqueConstraint('user_id', 'program_code', 'created_date', name='unique_user_program_date'),
    )

    def __repr__(self):
        return f'<UserPlaylist {self.playlist_name} ({self.spotify_playlist_id})>'


class SongCache(db.Model):
    """Model for caching song data from radio programs"""
    __tablename__ = 'song_cache'

    id = db.Column(db.Integer, primary_key=True)
    program_code = db.Column(db.String(100), nullable=False, index=True)
    cache_date = db.Column(db.Date, nullable=False)

    # Songs stored as JSON
    songs_json = db.Column(db.Text, nullable=False)

    # Timestamps
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Composite unique constraint
    __table_args__ = (
        db.UniqueConstraint('program_code', 'cache_date', name='unique_program_date_cache'),
    )

    def __repr__(self):
        return f'<SongCache {self.program_code} {self.cache_date}>'
