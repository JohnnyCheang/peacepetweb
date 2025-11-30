import os
from datetime import datetime
from functools import wraps

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from vercel_blob import delete, put
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "peacepet_luxury_cms_secret_key_change_me"
)

# 1. 扩充字体选项 (Issue 2)
FONT_OPTIONS = [
    "Playfair Display",
    "Lato",
    "Arial",
    "Helvetica",
    "Georgia",
    "Verdana",
    "Times New Roman",
    "Courier New",
    "Montserrat",
    "Roboto",
    "Open Sans",
    "Garamond",
    "Palatino",
    "Bookman",
    "Trebuchet MS",
]


# --- Database and Auth ---


@app.context_processor
def inject_common():
    return {
        "FONT_OPTIONS": FONT_OPTIONS,
        "now": datetime.now,
        "is_admin": session.get("is_admin", False),
    }


def get_db_conn():
    conn = psycopg2.connect(os.environ.get("POSTGRES_URL_NON_POOLING"))
    conn.cursor_factory = psycopg2.extras.DictCursor
    return conn


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            flash("You need to be logged in to access this page.", "error")
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


# --- App Lifecycle ---


@app.before_request
def set_language_and_nav():
    if "lang" not in session:
        session["lang"] = "en"
    g.lang = session["lang"]
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM categories ORDER BY sort_order DESC, id DESC")
    g.categories = c.fetchall()
    c.execute("SELECT * FROM settings")
    g.settings = {row["key"]: row["value"] for row in c.fetchall()}
    conn.close()


# --- Auth Routes ---


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("is_admin"):
        return redirect(url_for("admin"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == "adminJ" and password == "141225":
            session["is_admin"] = True
            flash("Login successful!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("admin"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# --- Language and Public Routes ---


@app.route("/switch_lang/<new_lang>")
def switch_lang(new_lang):
    if new_lang in ["en", "zh"]:
        session["lang"] = new_lang
    return redirect(request.referrer or url_for("index"))


# --- 前台路由 ---
@app.route("/")
def index():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE is_featured = 1 ORDER BY id DESC LIMIT 6")
    products = c.fetchall()
    conn.close()
    return render_template("index.html", products=products)


@app.route("/about")
def about():
    about_images_data = [
        {
            "key": "about_image_1",
            "src": g.settings.get("about_image_1"),
            "caption_en": g.settings.get("about_caption_1_en"),
            "caption_zh": g.settings.get("about_caption_1_zh"),
        },
        {
            "key": "about_image_2",
            "src": g.settings.get("about_image_2"),
            "caption_en": g.settings.get("about_caption_2_en"),
            "caption_zh": g.settings.get("about_caption_2_zh"),
        },
        {
            "key": "about_image_3",
            "src": g.settings.get("about_image_3"),
            "caption_en": g.settings.get("about_caption_3_en"),
            "caption_zh": g.settings.get("about_caption_3_zh"),
        },
    ]
    return render_template("about.html", about_images_data=about_images_data)


@app.route("/catalog")
def catalog_index():
    return render_template("catalog_index.html")


@app.route("/deals")
def deals():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE is_deal = 1 ORDER BY id DESC")
    products = c.fetchall()
    conn.close()
    return render_template("deals.html", products=products)


@app.route("/new_arrivals")
def new_arrivals():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE is_new = 1 ORDER BY id DESC")
    products = c.fetchall()
    conn.close()
    return render_template("new_arrivals.html", products=products)


@app.route("/catalog/<slug>")
def category_detail(slug):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM categories WHERE slug = %s", (slug,))
    category = c.fetchone()
    if not category:
        abort(404)
    c.execute(
        "SELECT * FROM products WHERE category_id = %s ORDER BY id DESC",
        (category["id"],),
    )
    products = c.fetchall()
    conn.close()
    return render_template("category_detail.html", products=products, category=category)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = c.fetchone()
    if not product:
        abort(404)
    c.execute(
        "SELECT * FROM feedback WHERE product_id = %s ORDER BY id DESC", (product_id,)
    )
    reviews = c.fetchall()
    conn.close()
    bullets_field = f"bullet_points_{g.lang}"
    bullets = product[bullets_field].split("\n") if product[bullets_field] else []
    a_plus_imgs = (
        product["a_plus_images"].split(",") if product["a_plus_images"] else []
    )
    return render_template(
        "product.html",
        product=product,
        bullets=bullets,
        a_plus_imgs=a_plus_imgs,
        reviews=reviews,
    )


@app.route("/submit_order", methods=["POST"])
def submit_order():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO orders (product_name, customer_name, contact_info, note, date) VALUES (%s, %s, %s, %s, %s)",
        (
            request.form.get("product_name"),
            request.form.get("customer_name"),
            request.form.get("contact"),
            request.form.get("note", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    conn.commit()
    conn.close()
    return "OK"


# --- 后台管理路由 ---


@app.route("/admin/delete/category/<int:cat_id>")
@admin_required
def delete_category(cat_id):
    conn = get_db_conn()
    c = conn.cursor()
    # Also delete image from blob storage
    c.execute("SELECT image FROM categories WHERE id = %s", (cat_id,))
    image_url = c.fetchone()["image"]
    if image_url:
        try:
            delete(image_url)
        except Exception as e:
            flash(f"Could not delete image from blob storage: {e}", "error")
    c.execute("DELETE FROM categories WHERE id = %s", (cat_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin", tab="categories"))


@app.route("/admin/delete/product/<int:product_id>")
@admin_required
def delete_product(product_id):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute(
        "SELECT main_image, a_plus_images FROM products WHERE id = %s", (product_id,)
    )
    product = c.fetchone()
    if product["main_image"]:
        try:
            delete(product["main_image"])
        except Exception as e:
            flash(f"Could not delete main image from blob storage: {e}", "error")
    if product["a_plus_images"]:
        urls = product["a_plus_images"].split(",")
        try:
            delete(urls)
        except Exception as e:
            flash(f"Could not delete A+ images from blob storage: {e}", "error")

    c.execute("DELETE FROM products WHERE id = %s", (product_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin", tab="products"))


@app.route("/admin/edit_product/<int:product_id>", methods=["GET", "POST"])
@admin_required
def edit_product(product_id):
    conn = get_db_conn()
    c = conn.cursor()
    if request.method == "POST":
        c.execute(
            "SELECT main_image, a_plus_images FROM products WHERE id = %s",
            (product_id,),
        )
        product_data = c.fetchone()

        main_image_url = product_data["main_image"]
        main_img_file = request.files.get("main_image")
        if main_img_file and main_img_file.filename:
            if main_image_url:  # Delete old one
                try:
                    delete(main_image_url)
                except Exception as e:
                    flash(f"Could not delete old main image: {e}", "error")
            filename = "main_" + secure_filename(main_img_file.filename)
            blob = put(f"uploads/{filename}", main_img_file.read())
            main_image_url = blob["url"]

        a_plus_urls = product_data["a_plus_images"]
        a_plus_files = request.files.getlist("a_plus_images")
        if a_plus_files and a_plus_files[0].filename:  # If new files are uploaded
            if a_plus_urls:  # Delete old ones
                try:
                    delete(a_plus_urls.split(","))
                except Exception as e:
                    flash(f"Could not delete old A+ images: {e}", "error")

            new_urls = []
            for file in a_plus_files:
                if file and file.filename:
                    fname = "aplus_" + secure_filename(file.filename)
                    blob = put(f"uploads/{fname}", file.read())
                    new_urls.append(blob["url"])
            a_plus_urls = ",".join(new_urls)

        c.execute(
            """UPDATE products SET category_id=%s, title_en=%s, title_zh=%s, price=%s, main_image=%s, bullet_points_en=%s, bullet_points_zh=%s, description_en=%s, description_zh=%s, a_plus_images=%s, monthly_sales=%s, avg_rating=%s, is_new=%s, is_deal=%s, is_featured=%s WHERE id=%s""",
            (
                request.form.get("category_id"),
                request.form.get("title_en"),
                request.form.get("title_zh"),
                request.form.get("price"),
                main_image_url,
                request.form.get("bullet_points_en", ""),
                request.form.get("bullet_points_zh", ""),
                request.form.get("description_en", ""),
                request.form.get("description_zh", ""),
                a_plus_urls,
                request.form.get("monthly_sales", 0),
                request.form.get("avg_rating", 5.0),
                1 if request.form.get("is_new") == "on" else 0,
                1 if request.form.get("is_deal") == "on" else 0,
                1 if request.form.get("is_featured") == "on" else 0,
                product_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("admin"))

    c.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = c.fetchone()
    c.execute("SELECT id, name_zh, name_en FROM categories")
    categories_list = c.fetchall()
    conn.close()
    a_plus_imgs = (
        product["a_plus_images"].split(",") if product["a_plus_images"] else []
    )
    return render_template(
        "edit_product.html",
        product=product,
        categories_list=categories_list,
        a_plus_imgs=a_plus_imgs,
    )


@app.route("/admin/edit_category/<int:cat_id>", methods=["GET", "POST"])
@admin_required
def edit_category(cat_id):
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM categories WHERE id = %s", (cat_id,))
    category = c.fetchone()
    if request.method == "POST":
        cat_image_url = category["image"]

        if request.form.get("delete_image") == "on":
            if cat_image_url:
                try:
                    delete(cat_image_url)
                except Exception as e:
                    flash(f"Could not delete image: {e}", "error")
            cat_image_url = ""
        else:
            cat_img_file = request.files.get("category_image")
            if cat_img_file and cat_img_file.filename:
                if cat_image_url:  # Delete old one
                    try:
                        delete(cat_image_url)
                    except Exception as e:
                        flash(f"Could not delete old image: {e}", "error")
                cat_filename = "cat_" + secure_filename(cat_img_file.filename)
                blob = put(f"uploads/{cat_filename}", cat_img_file.read())
                cat_image_url = blob["url"]

        c.execute(
            "UPDATE categories SET name_en=%s, name_zh=%s, slug=%s, image=%s, sort_order=%s WHERE id=%s",
            (
                request.form.get("name_en"),
                request.form.get("name_zh"),
                request.form.get("slug", "").lower().replace(" ", "-"),
                cat_image_url,
                request.form.get("sort_order", 0),
                cat_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("admin", tab="categories"))
    conn.close()
    return render_template("edit_category.html", category=category)


@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    conn = get_db_conn()
    c = conn.cursor()

    def handle_single_upload(file_key, setting_key, delete_key, prefix):
        old_url = g.settings.get(setting_key)
        if request.form.get(delete_key) == "on":
            if old_url:
                try:
                    delete(old_url)
                except Exception as e:
                    flash(f"Could not delete blob: {e}", "error")
            c.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (setting_key, ""),
            )
        else:
            img_file = request.files.get(file_key)
            if img_file and img_file.filename:
                if old_url:
                    try:
                        delete(old_url)
                    except Exception as e:
                        flash(f"Could not delete old blob: {e}", "error")
                img_filename = prefix + "_" + secure_filename(img_file.filename)
                blob = put(f"uploads/{img_filename}", img_file.read())
                c.execute(
                    "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (setting_key, blob["url"]),
                )

    if request.method == "POST":
        action = request.form.get("admin_action")

        if action == "UPDATE_SETTINGS":
            handle_single_upload("site_logo_file", "site_logo", "delete_logo", "logo")

            banner_type = request.form.get("hero_banner_type")
            c.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                ("hero_banner_type", banner_type),
            )
            if banner_type == "url":
                c.execute(
                    "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    ("hero_banner_url", request.form.get("hero_banner_url", "")),
                )
            else:
                handle_single_upload(
                    "hero_banner_upload_file",
                    "hero_banner_upload",
                    "delete_hero_banner_upload",
                    "hero",
                )

            handle_single_upload(
                "home_slogan_image_file",
                "home_slogan_img",
                "delete_home_slogan_image",
                "home_slogan",
            )
            handle_single_upload(
                "deals_banner_file",
                "deals_banner_upload",
                "delete_deals_banner",
                "deals_banner",
            )
            handle_single_upload(
                "new_banner_file",
                "new_banner_upload",
                "delete_new_banner",
                "new_banner",
            )

            for i in range(1, 4):
                handle_single_upload(
                    f"about_image_{i}_file",
                    f"about_image_{i}",
                    f"delete_about_image_{i}",
                    f"about_{i}",
                )

            excluded = [
                "admin_action",
                "csrf_token",
                "site_logo_file",
                "delete_logo",
                "hero_banner_upload_file",
                "delete_hero_banner_upload",
                "home_slogan_image_file",
                "delete_home_slogan_image",
                "deals_banner_file",
                "delete_deals_banner",
                "new_banner_file",
                "delete_new_banner",
                "about_image_1_file",
                "delete_about_image_1",
                "about_image_2_file",
                "delete_about_image_2",
                "about_image_3_file",
                "delete_about_image_3",
                "hero_banner_url",
                "hero_banner_type",
            ]

            for key, value in request.form.items():
                if key not in excluded:
                    c.execute(
                        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (key, value),
                    )

            conn.commit()
            return redirect(url_for("admin", tab="settings"))

        elif action == "ADD_PRODUCT":
            main_image_url = ""
            main_img_file = request.files.get("main_image")
            if main_img_file and main_img_file.filename:
                filename = "main_" + secure_filename(main_img_file.filename)
                blob = put(f"uploads/{filename}", main_img_file.read())
                main_image_url = blob["url"]

            a_plus_urls = []
            a_plus_files = request.files.getlist("a_plus_images")
            for file in a_plus_files:
                if file and file.filename:
                    fname = "aplus_" + secure_filename(file.filename)
                    blob = put(f"uploads/{fname}", file.read())
                    a_plus_urls.append(blob["url"])
            a_plus_str = ",".join(a_plus_urls)

            c.execute(
                """INSERT INTO products (category_id, title_en, title_zh, price, main_image, bullet_points_en, bullet_points_zh, description_en, description_zh, a_plus_images, monthly_sales, avg_rating, is_new, is_deal, is_featured) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    request.form.get("category_id"),
                    request.form.get("title_en"),
                    request.form.get("title_zh"),
                    request.form.get("price"),
                    main_image_url,
                    request.form.get("bullet_points_en", ""),
                    request.form.get("bullet_points_zh", ""),
                    request.form.get("description_en", ""),
                    request.form.get("description_zh", ""),
                    a_plus_str,
                    request.form.get("monthly_sales", 0),
                    request.form.get("avg_rating", 5.0),
                    1 if request.form.get("is_new") == "on" else 0,
                    1 if request.form.get("is_deal") == "on" else 0,
                    1 if request.form.get("is_featured") == "on" else 0,
                ),
            )
            conn.commit()
            return redirect(url_for("admin", tab="products"))

        elif action == "ADD_CATEGORY":
            cat_image_url = ""
            cat_img_file = request.files.get("category_image")
            if cat_img_file and cat_img_file.filename:
                cat_filename = "cat_" + secure_filename(cat_img_file.filename)
                blob = put(f"uploads/{cat_filename}", cat_img_file.read())
                cat_image_url = blob["url"]

            c.execute(
                "INSERT INTO categories (name_en, name_zh, slug, image, sort_order) VALUES (%s, %s, %s, %s, %s)",
                (
                    request.form.get("name_en"),
                    request.form.get("name_zh"),
                    request.form.get("slug", "").lower().replace(" ", "-"),
                    cat_image_url,
                    request.form.get("sort_order", 0),
                ),
            )
            conn.commit()
            return redirect(url_for("admin", tab="categories"))

        elif action == "ADD_FEEDBACK":
            img_url = ""
            feedback_img_file = request.files.get("feedback_image")
            if feedback_img_file and feedback_img_file.filename:
                img_filename = "fb_" + secure_filename(feedback_img_file.filename)
                blob = put(f"uploads/{img_filename}", feedback_img_file.read())
                img_url = blob["url"]

            c.execute(
                "INSERT INTO feedback (product_id, rating, text_en, text_zh, image) VALUES (%s, %s, %s, %s, %s)",
                (
                    request.form.get("product_id"),
                    request.form.get("rating", 5.0),
                    request.form.get("text_en", ""),
                    request.form.get("text_zh", ""),
                    img_url,
                ),
            )
            conn.commit()
            return redirect(url_for("admin", tab="feedback"))

    c.execute("SELECT * FROM orders ORDER BY id DESC")
    orders = c.fetchall()
    c.execute("SELECT * FROM categories ORDER BY sort_order DESC, id DESC")
    categories_list = c.fetchall()
    c.execute(
        "SELECT p.*, c.name_zh as category_name_zh, c.name_en as category_name_en FROM products p LEFT JOIN categories c ON p.category_id = c.id ORDER BY p.id DESC"
    )
    products_list = c.fetchall()

    about_images_data = [
        {
            "key": f"about_image_{i}",
            "src": g.settings.get(f"about_image_{i}"),
            "caption_en": g.settings.get(f"about_caption_{i}_en"),
            "caption_zh": g.settings.get(f"about_caption_{i}_zh"),
        }
        for i in range(1, 4)
    ]

    active_tab = request.args.get("tab", "products")
    conn.close()
    return render_template(
        "admin.html",
        orders=orders,
        categories_list=categories_list,
        products_list=products_list,
        categories=g.categories,
        settings_dict=g.settings,
        about_images_data=about_images_data,
        active_tab=active_tab,
    )
