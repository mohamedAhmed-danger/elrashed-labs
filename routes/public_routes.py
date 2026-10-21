from flask import Blueprint, render_template

from services.domain.laboratory_service import LaboratoryService

public_bp = Blueprint("public", __name__)


@public_bp.route("/about")
def about():
    return render_template("public/index.html", brand=LaboratoryService.get_public_brand())


@public_bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html", brand=LaboratoryService.get_public_brand())
