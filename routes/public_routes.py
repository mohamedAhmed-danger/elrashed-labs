from flask import Blueprint, render_template

public_bp = Blueprint("public", __name__)


@public_bp.route("/about")
def about():
    return render_template("public/index.html")


@public_bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html")