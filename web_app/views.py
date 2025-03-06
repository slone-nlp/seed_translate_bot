from app import DB, server, BASE_URL
from flask import Flask, request, session, render_template
from flask_babel import Babel, _  # noqa
from flask_babel import lazy_gettext as _l  # noqa
from flask_bcrypt import Bcrypt
from flask_login import current_user, LoginManager
import os

from flask import flash, redirect, render_template, request
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length, Regexp
from models import UserState, FlaskUser


##############
# Setup users
##############


server.secret_key = os.urandom(32)
bcrypt = Bcrypt(server)
# pw_hash = bcrypt.generate_password_hash('hunter2').decode(‘utf-8’)
# bcrypt.check_password_hash(pw_hash, 'hunter2') # returns True

login_manager = LoginManager()
login_manager.init_app(server)
login_manager.login_view = "view_login"
login_manager.login_message = None


@login_manager.user_loader
def load_user(userid):
    if isinstance(userid, str) and userid.lstrip("-").isnumeric():
        userid = int(userid)

    user_state = DB.find_user_account(user_id=userid)
    print(f"for user_id {userid} (of type {type(userid)}), found the user state {user_state} when loading a user")
    if user_state is None:
        return None  # according to flask-login documentation, this is what is required

    return FlaskUser.from_account(user_state)



##############
# Setup i18n
##############


APP_LANGS = ["en", "ru"]


def get_flask_locale():
    if session.get("lang_code") in APP_LANGS:
        return session["lang_code"]
    if current_user and current_user.is_authenticated and current_user.user_state:
        account = current_user.user_state
        if account.interface_lang in APP_LANGS:
            return account.interface_lang
    return request.accept_languages.best_match(APP_LANGS)


babel = Babel(
    server,
    locale_selector=get_flask_locale,
    default_translation_directories="interface_translations",
)


@server.context_processor
def inject_flask_locale():
    return dict(flask_locale=get_flask_locale())


##############
# The base views
##############


@server.route("/")
def view_home():
    return render_template("home.html")


##############
# List projects
##############


@server.route("/projects")
def view_projects():
    projects_list = DB.get_projects()
    return render_template("projects.html", projects_list=projects_list)

##############
# USER_MANAGEMENT
##############


LOGIN_DATA = {
    "bot_name": "crowd_translate_bot",
    "bot_domain": f"{BASE_URL}telegram-login-result",
}
TOKEN = os.environ.get("TOKEN", "DID_NOT_GET")


class RegistrationForm(FlaskForm):
    username = StringField(
        _l("Username"),
        validators=[
            DataRequired(),
            Length(min=6, max=40),
            Regexp(
                "^\\w+$",
                message=_l(
                    "Username must contain only letters, numbers, or underscores."
                ),
            ),
        ],
    )
    password = PasswordField(
        _l("Password"), validators=[DataRequired(), Length(min=6, max=25)]
    )
    confirm = PasswordField(
        _l("Repeat password"),
        validators=[
            DataRequired(),
            EqualTo("password", message=_l("Passwords must match.")),
        ],
    )

    def validate(self, extra_validators=None):
        initial_validation = super(RegistrationForm, self).validate(
            extra_validators=extra_validators
        )
        if not initial_validation:
            return False
        existing_account = DB.find_user_account(username=self.username.data)
        if existing_account:
            self.username.append(_l("Username already registered."))
            return False
        if self.password.data != self.confirm.data:
            self.password.errors.append(_l("Passwords must match."))
            return False
        return True


class LoginForm(FlaskForm):
    username = StringField(_l("Username"), validators=[DataRequired()])
    password = PasswordField(_l("Password"), validators=[DataRequired()])


@server.route("/login", methods=["GET", "POST"])
def view_login():
    if current_user.is_authenticated:
        flash("You are already logged in.", "info")
        return redirect("/")
    form = LoginForm(request.form)
    if form.validate_on_submit():
        account = DB.find_user_account(username=form.username.data)
        if (
            account
            and account.password_hash
            and bcrypt.check_password_hash(
                account.password_hash, request.form["password"]
            )
        ):
            user = FlaskUser.from_account(account)
            login_user(
                user, remember=True
            )  # TODO: make the "remember me" option in the form
            if request.args.get("next"):
                return redirect(request.args.get("next"))
            else:
                return redirect("/")
        else:
            flash(_("Invalid username and/or password."), "danger")
            return render_template(
                "login.html",
                form=form,
                login_data=LOGIN_DATA,
                current_user=current_user,
            )
    return render_template(
        "login.html", form=form, login_data=LOGIN_DATA, current_user=current_user
    )


def string_generator(data_incoming):
    # this is a generator for the Telegram login widget
    data = data_incoming.copy()
    del data["hash"]
    keys = sorted(data.keys())
    string_arr = []
    for key in keys:
        if data[key] is not None:
            # expecting all the values to be strings
            string_arr.append(key + "=" + data[key])
    string_cat = "\n".join(string_arr)
    return string_cat


@server.route("/telegram-login-result")
def telegram_login_result():
    tg_data = {
        "id": request.args.get("id", None),
        "first_name": request.args.get("first_name", None),
        "last_name": request.args.get("last_name", None),
        "username": request.args.get("username", None),
        "photo_url": request.args.get("photo_url", None),
        "auth_date": request.args.get("auth_date", None),
        "hash": request.args.get("hash", None),
    }
    data_check_string = string_generator(tg_data)
    secret_key = hashlib.sha256(TOKEN.encode("utf-8")).digest()
    secret_key_bytes = secret_key
    data_check_string_bytes = bytes(data_check_string, "utf-8")
    hmac_string = hmac.new(
        secret_key_bytes, data_check_string_bytes, hashlib.sha256
    ).hexdigest()
    if hmac_string == tg_data["hash"] and tg_data["id"] is not None:
        tg_id = int(tg_data["id"])
        # TODO: fix this lookup
        account = DB.find_user_account(tg_id=tg_id)
        if account is None:
            flash(
                f"Telegram-based account for id {tg_id} was not found; creating a new one!",
                "info",
            )
            # TODO: implement this creation
            account = DB.create_user_with_telegram_data(
                tg_id=tg_id,
                tg_username=tg_data["username"],
                first_name=tg_data["first_name"],
                last_name=tg_data["last_name"],
            )
        else:
            flash("Telegram-based account was found; logging you in!", "info")

        if account:
            user = FlaskUser.from_account(account=account)
            login_user(user, remember=True)
            if request.args.get("next"):
                return redirect(request.args.get("next"))
            else:
                return redirect("/")

    if tg_data["id"] is None:
        flash(
            "Your telegram id is empty. Please contact the admins to debug the problem.",
            "danger",
        )

    flash(
        "Your Telegram authorization data does not seem to be matching. Please try again or contact the admins.",
        "danger",
    )
    return redirect("/login")


@server.route("/register", methods=["GET", "POST"])
def view_register():
    if current_user.is_authenticated:
        flash("You are already registered.", "info")
        return redirect("/")

    form = RegistrationForm(request.form)
    if form.validate_on_submit():
        username = form.username.data
        if len(username) < 4:
            flash(f"The username {username} is too short; please choose at least 4 characters!")
            return render_template("register.html", form=form, current_user=current_user)

        other = DB.find_user_account(username=username)
        if other:
            flash(f"Account with the name {username} already exists!")
            return render_template("register.html", form=form, current_user=current_user)

        pw_hash = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
        account = DB.create_user_with_password(
            username=username, password_hash=pw_hash
        )
        user = FlaskUser.from_account(account)
        login_user(user, remember=True)
        flash(_("You registered and are now logged in. Welcome!"), "success")

        return redirect("/")

    return render_template("register.html", form=form, current_user=current_user)


@server.route("/logout")
@login_required
def logout_page():
    logout_user()
    flash(_("You have successfully logged out."), "success")
    return redirect("/")
