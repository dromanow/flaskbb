# -*- coding: utf-8 -*-
"""
    flaskbb.auth.views
    ~~~~~~~~~~~~~~~~~~~~

    This view provides user authentication, registration and a view for
    resetting the password of a user if he has lost his password

    :copyright: (c) 2014 by the FlaskBB Team.
    :license: BSD, see LICENSE for more details.
"""
from flask import Blueprint, flash, redirect, url_for, request, current_app
from flask_login import (current_user, login_user, login_required,
                         logout_user, confirm_login, login_fresh)
from flask_babelplus import gettext as _

from flaskbb.utils.helpers import render_template
from flaskbb.email import send_reset_token
from flaskbb.auth.forms import (LoginForm, ReauthForm, ForgotPasswordForm,
                                ResetPasswordForm)
from flaskbb.user.models import User
from flaskbb.fixtures.settings import available_languages
from flaskbb.utils.settings import flaskbb_config

import requests
import json
from datetime import datetime


auth = Blueprint("auth", __name__)


def auth_cabinet_user(username, password):
    req = requests.post(current_app.config['CABINET_AUTH'], json={"login": username, "password": password})
    if req.status_code != 200 or not req.text:
        current_app.logger.error('requests.post to {} failed'.format(current_app.config['CABINET_AUTH']))
        return False

    res = json.loads(req.text)
    status = res.get('status')
    if status != 'OK':
        current_app.logger.warning('auth_cabinet_user: {}'.format(req.text))
        return False, None

    return True, res.get('email', None)


@auth.route("/login", methods=["GET", "POST"])
def login():
    """
    Logs the user in
    """

    if current_user is not None and current_user.is_authenticated:
        return redirect(url_for("user.profile"))

    form = LoginForm(request.form)
    if form.validate_on_submit():
        user, authenticated = User.authenticate(form.login.data,
                                                form.password.data)

        if user and authenticated:
            login_user(user, remember=form.remember_me.data)
            return redirect(request.args.get("next") or
                            url_for("forum.index"))
        else:
            result, email = auth_cabinet_user(form.login.data, form.password.data)
            if result:
                user = User(username=form.login.data,
                            email=email or 'unknown',
                            password=form.password.data,
                            date_joined=datetime.utcnow(),
                            primary_group_id=4)
                user.save()
                login_user(user, remember=form.password.data)
                return redirect(request.args.get("next") or
                                url_for("forum.index"))

        flash(_("Wrong Username or Password."), "danger")
    return render_template("auth/login.html", form=form)


@auth.route("/reauth", methods=["GET", "POST"])
@login_required
def reauth():
    """
    Reauthenticates a user
    """

    if not login_fresh():
        form = ReauthForm(request.form)
        if form.validate_on_submit():
            if current_user.check_password(form.password.data):
                confirm_login()
                flash(_("Reauthenticated."), "success")
                return redirect(request.args.get("next") or current_user.url)

            flash(_("Wrong password."), "danger")
        return render_template("auth/reauth.html", form=form)
    return redirect(request.args.get("next") or current_user.url)


@auth.route("/logout")
@login_required
def logout():
    logout_user()
    flash(_("Logged out"), "success")
    return redirect(url_for("forum.index"))


def create_cabinet_user(username, password, email):
    req = requests.post(current_app.config['CABINET_REGISTER'],
                        json={"login": username, "password": password, 'email': email})
    if req.status_code != 200 or not req.text:
        current_app.logger.error('requests.post to {} failed'.format(current_app.config['CABINET_REGISTER']))
        return False

    res = json.loads(req.text)
    status = res.get('status')
    if status != 'OK':
        current_app.logger.warning('create_cabinet_user: {}'.format(req.text))
        return False

    return True


@auth.route("/register", methods=["GET", "POST"])
def register():
    """
    Register a new user
    """

    if current_user is not None and current_user.is_authenticated:
        return redirect(url_for("user.profile",
                                username=current_user.username))

    if current_app.config["RECAPTCHA_ENABLED"]:
        from flaskbb.auth.forms import RegisterRecaptchaForm
        form = RegisterRecaptchaForm(request.form)
    else:
        from flaskbb.auth.forms import RegisterForm
        form = RegisterForm(request.form)

    form.language.choices = available_languages()
    form.language.default = flaskbb_config['DEFAULT_LANGUAGE']
    form.process(request.form)  # needed because a default is overriden

    if form.validate_on_submit():
        user = form.save()
        create_cabinet_user(user.username, user.password, user.email)
        login_user(user)

        flash(_("Thanks for registering."), "success")
        return redirect(url_for("user.profile",
                                username=current_user.username))

    return render_template("auth/register.html", form=form)


@auth.route('/resetpassword', methods=["GET", "POST"])
def forgot_password():
    """
    Sends a reset password token to the user.
    """

    if not current_user.is_anonymous:
        return redirect(url_for("forum.index"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user:
            token = user.make_reset_token()
            send_reset_token(user, token=token)

            flash(_("E-Mail sent! Please check your inbox."), "info")
            return redirect(url_for("auth.forgot_password"))
        else:
            flash(_("You have entered a Username or E-Mail Address that is "
                    "not linked with your account."), "danger")
    return render_template("auth/forgot_password.html", form=form)


@auth.route("/resetpassword/<token>", methods=["GET", "POST"])
def reset_password(token):
    """
    Handles the reset password process.
    """

    if not current_user.is_anonymous:
        return redirect(url_for("forum.index"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        expired, invalid, data = user.verify_reset_token(form.token.data)

        if invalid:
            flash(_("Your Password Token is invalid."), "danger")
            return redirect(url_for("auth.forgot_password"))

        if expired:
            flash(_("Your Password Token is expired."), "danger")
            return redirect(url_for("auth.forgot_password"))

        if user and data:
            user.password = form.password.data
            user.save()
            flash(_("Your Password has been updated."), "success")
            return redirect(url_for("auth.login"))

    form.token.data = token
    return render_template("auth/reset_password.html", form=form)
