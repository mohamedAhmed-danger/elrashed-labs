from models.models import User, db


class UserService:
    # Initializes a new instance of UserService with optional user ID or entity
    def __init__(self, user_id=None, user=None):
        """
        Initializes the UserService instance.

        Input:
            - user_id (int, optional): Unique identifier of the user. Defaults to None.
            - user (User, optional): Pre-fetched User model instance. Defaults to None.

        Processing:
            - Assigns user_id to self.user_id.
            - Stores pre-fetched user model instance in self._user.

        Output:
            - None: Initializes class instance attributes.
        """
        self.user_id = user_id
        self._user = user

    # Retrieves or lazily loads the User entity associated with this instance
    @property
    def user(self):
        """
        Property that lazily retrieves the User model instance.

        Input:
            - None: Uses instance attributes self.user_id and self._user.

        Processing:
            - Checks if self._user is already cached.
            - If not cached and self.user_id is provided, fetches the user from the database via db.session.get.
            - Caches and returns the User model instance.

        Output:
            - User or None: The cached or fetched User instance, or None if not found.
        """
        if self._user is None and self.user_id is not None:
            self._user = db.session.get(User, self.user_id)
        return self._user

    # Retrieves a user by their unique ID or from instance cache
    def get_user(self, user_id=None):
        """
        Fetches a user from the database using instance user_id or provided user_id.

        Input:
            - user_id (int, optional): The unique ID of the user. Defaults to self.user_id.

        Processing:
            - Resolves target ID from the user_id argument or self.user_id.
            - Checks if self._user is already loaded and matches target ID.
            - Queries the database using db.session.get(User, target_id).
            - Updates self._user and self.user_id if target ID matches the instance.

        Output:
            - tuple: (User instance if found else None, message string)
        """
        target_id = user_id or self.user_id
        if not target_id and self._user:
            return self._user, "تم العثور على المستخدم"
        if not target_id:
            return None, "المستخدم غير موجود"

        if self._user and self._user.id == target_id:
            return self._user, "تم العثور على المستخدم"

        try:
            user = db.session.get(User, target_id)
            if user:
                if target_id == self.user_id or self.user_id is None:
                    self._user = user
                    self.user_id = user.id
                return user, "تم العثور على المستخدم"
            else:
                return None, "المستخدم غير موجود"
        except Exception as e:
            return None, str(e)

    # Backward-compatible alias for get_user
    def get_user_by_id(self, user_id=None):
        """
        Backward-compatible alias for get_user.

        Input:
            - user_id (int, optional): The unique ID of the user. Defaults to self.user_id.

        Processing:
            - Delegates directly to self.get_user(user_id=user_id).

        Output:
            - tuple: (User instance if found else None, message string)
        """
        return self.get_user(user_id=user_id)

    # Updates an existing user's details including name and password
    def update_user(self, name=None, password=None, user_id=None):
        """
        Updates the information of an existing user.

        Input:
            - name (str, optional): The new username.
            - password (str, optional): The new password.
            - user_id (int, optional): The user ID (defaults to self.user_id).

        Processing:
            - Resolves target user from cache or db.session.get.
            - Validates that the user exists.
            - If name is changed, checks if another user already has that name.
            - Updates name and/or password fields if provided.
            - Commits changes to the database and updates instance cache.
            - Rolls back session if an error occurs.

        Output:
            - tuple: (Updated User instance if successful else None, message string)
        """
        try:
            target_id = user_id or self.user_id
            user = None
            if self._user and (not target_id or self._user.id == target_id):
                user = self._user
            elif target_id:
                user = db.session.get(User, target_id)

            if not user:
                return None, "المستخدم غير موجود"

            if name:
                name = name.strip().lower()
                if name != user.name:
                    the_user = User.query.filter_by(name=name).first()
                    if the_user:
                        return None, "اسم المستخدم موجود بالفعل"
                    user.name = name

            if password:
                user.password = password

            db.session.commit()
            self._user = user
            self.user_id = user.id
            return user, "تم تحديث المستخدم بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء التحديث: {str(e)}"

    # Creates a new user record in the database
    def create_user(self, name, password):
        """
        Creates a new user in the database.

        Input:
            - name (str): The username for the new account.
            - password (str): The password for the new account.

        Processing:
            - Strips and lowercases the username.
            - Checks if a user with the same name already exists in the database.
            - Adds the new User entity and commits to the database.
            - Updates self._user and self.user_id on success.
            - Rolls back on error.

        Output:
            - tuple: (User instance if successful else None, message string)
        """
        try:
            name = name.strip().lower()
            existing_user = User.query.filter_by(name=name).first()
            if existing_user:
                return None, "اسم المستخدم موجود بالفعل"

            new_user = User(name=name, password=password)
            db.session.add(new_user)
            db.session.commit()
            self._user = new_user
            self.user_id = new_user.id
            return new_user, "تم إنشاء المستخدم بنجاح"
        except Exception as e:
            db.session.rollback()
            return None, f"حدث خطأ أثناء إنشاء المستخدم: {str(e)}"


    # Authenticates a user and returns the model entity directly
    def authenticate(self, username, password):
        """
        Authenticates a user and returns the user object directly.

        Input:
            - username (str): The username.
            - password (str): The password.

        Processing:
            - Queries User matching both username and password.
            - Updates self._user and self.user_id if a user is found.

        Output:
            - User or None: User instance if authentication succeeds, otherwise None.
        """
        user = User.query.filter_by(name=username, password=password).first()
        if user:
            self._user = user
            self.user_id = user.id
        return user

    # Retrieves all user records from the database
    def get_all_users(self):
        """
        Fetches all registered users from the database.

        Input:
            - None

        Processing:
            - Queries all records from the User table using User.query.all().

        Output:
            - list: A list of all User objects in the database.
        """
        return User.query.all()