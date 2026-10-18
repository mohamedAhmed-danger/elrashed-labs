from flask import Blueprint, render_template, request, redirect, url_for, flash
from services.domain.bundle_service import (
    BundleService, MAX_BUNDLES, BUNDLE_LIMIT_REACHED_MSG,
)
bundle_bp = Blueprint("bundle", __name__, url_prefix="/bundles")


@bundle_bp.route("/", methods=["GET"])
def list_bundles():
    bundles = BundleService.get_all_bundles()
    return render_template(
        "bundles/list.html", bundles=bundles, max_bundles=MAX_BUNDLES
    )


@bundle_bp.route("/add", methods=["GET", "POST"])
def add_bundle():
    if not BundleService.can_add_bundle():
        flash(BUNDLE_LIMIT_REACHED_MSG, "danger")
        return redirect(url_for("bundle.list_bundles"))
    if request.method == "POST":
        name = request.form.get("name")
        price = request.form.get("price")
        description = request.form.get("description")
        instructions = request.form.get("instructions")

        service = BundleService()
        bundle, msg = service.create_bundle(
            name=name,
            price=price,
            description=description,
            instructions=instructions,
        )

        if bundle:
            flash(msg, "success")
            return redirect(url_for("bundle.list_bundles"))

        flash(msg, "danger")
        # نرجّع القيم المكتوبة عشان ما تتمسحش لما يحصل خطأ
        return render_template("bundles/add.html", form=request.form)

    return render_template("bundles/add.html", form={})


@bundle_bp.route("/<int:bundle_id>", methods=["GET", "POST"])
def bundle_detail(bundle_id):
    service = BundleService(bundle_id=bundle_id)
    bundle, msg = service.get_bundle()

    if not bundle:
        flash(msg, "danger")
        return redirect(url_for("bundle.list_bundles"))

    if request.method == "POST":
        updated_bundle, update_msg = service.update_bundle(
            name=request.form.get("name"),
            price=request.form.get("price"),
            description=request.form.get("description"),
            instructions=request.form.get("instructions"),
        )
        if updated_bundle:
            flash(update_msg, "success")
            return redirect(url_for("bundle.list_bundles"))

        flash(update_msg, "danger")

    return render_template("bundles/detail.html", bundle=bundle)


@bundle_bp.route("/<int:bundle_id>/delete", methods=["POST"])
def delete_bundle(bundle_id):
    service = BundleService(bundle_id=bundle_id)
    deleted, msg = service.delete_bundle()
    flash(msg, "success" if deleted else "danger")
    return redirect(url_for("bundle.list_bundles"))