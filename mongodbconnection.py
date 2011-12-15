import pymongo
from simpleapi.exceptions import *
from time import time
from datetime import datetime
import base64
import uuid
import hmac
import hashlib

class MongoDBSession():
  _verified = False
  user_id = None
  session_id = None
  expires = 0
  state = {}
  __db = None
  
  def __init__(self, db, session_data):
    self.__db = db
    self.user_id = session_data['user_id']
    self.expires = session_data['expires']
    self.session_id = session_data['session_id']
    self.state = 'state' in session_data and session_data['state'] or {}

  def save_state(self):
    if not self._verified:
      raise RPCError(ERROR_NOT_AUTHORIZED, "Not authorized")
    self.__db.sessions.update({'session_id': session_id}, {'$set': {'state': self.state}})

class MongoDBConnection():
  password_salt = "simple_api" 
  default_session_ttl = 24 * 60 * 60

  def __init__(self, host, port, database):
    self.db = pymongo.Connection(host, port)[database]

  def password_hash(self, user_id, password):
    return hashlib.sha256(user_id + self.password_salt + password).hexdigest()

  def create_account(self, user_id, password):
    if self.db.accounts.find_one({'user_id': user_id}):
      raise RPCError(ERROR_USER_ID_EXISTS, "User ID already in use.")
    self.db.accounts.insert({'user_id': user_id, 'password': self.password_hash(user_id, password)})

  def create_session(self, user_id, password, ttl=0):
    expires = time() + (ttl or self.default_session_ttl)
    account = self.db.accounts.find_one({'user_id': user_id, 'password': self.password_hash(user_id, password)})
    if not account:
      raise RPCError(ERROR_USER_NOT_FOUND, "Invalid user ID or password")
    session_id = base64.b64encode(uuid.uuid4().bytes)
    self.db.sessions.remove({'user_id': user_id, 'expires': {'$lt': time()}})
    self.db.sessions.insert({'user_id': user_id, 'expires': expires, 'session_id': session_id})
    session = MongoDBSession(self.db, {'user_id': user_id, 'expires': expires, 'session_id': session_id, 'state':{}})
    return session

  def retrieve_session(self, session_id, hmac_data, data):
    session_data = self.db.sessions.find_one({'session_id': session_id, 'expires': {'$gt': time()}})
    if not session_data:
      raise RPCError(ERROR_INVALID_SESSION_ID, "Invalid session ID")
    session = MongoDBSession(self.db, session_data)
    if not hmac_data or hmac_data != hmac.new(str(session_data['user_id']), data, hashlib.sha1).hexdigest():
      raise RPCError(ERROR_INVALID_HMAC, "Invalid HMAC")
    session._verified = True
    return session

  def clear_sessions(self, user_id):
    self.db.sessions.remove({'user_id': user_id})

  def change_password(self, user_id, password, new_password):
    account = self.db.accounts.find_one({'user_id': user_id, 'password': self.password_hash(user_id, password)})
    if not account:
      raise RPCError(ERROR_USER_NOT_FOUND, "Invalid user ID or password")
    self.db.accounts.update({'user_id': user_id, 'password': self.password_hash(user_id, password)}, {'$set': {'password': self.password_hash(user_id, new_password)}})
    self.clear_sessions(user_id)

