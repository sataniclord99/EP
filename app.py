from flask import Flask, render_template, request, redirect, url_for, flash, abort, session, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors as pg_errors
from config import Config
import math
import traceback
from functools import wraps
from material_calculator import MaterialCalculator

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

material_calculator = MaterialCalculator()

def handle_db_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except psycopg2.OperationalError as e:
            flash('Ошибка подключения к базе данных. Пожалуйста, проверьте соединение.', 'error')
            app.logger.error(f"Database connection error: {e}")
            return render_template('error.html', 
                                 error_title="Ошибка подключения",
                                 error_message="Не удалось подключиться к базе данных. Проверьте настройки подключения.",
                                 back_url=url_for('index'))
        except Exception as e:
            flash(f'Произошла непредвиденная ошибка: {str(e)}', 'error')
            app.logger.error(f"Unexpected error: {traceback.format_exc()}")
            return render_template('error.html',
                                 error_title="Внутренняя ошибка",
                                 error_message="Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.",
                                 back_url=url_for('index'))
    return decorated_function

def get_db_connection():
    """Получение соединения с базой данных с обработкой ошибок"""
    try:
        conn = psycopg2.connect(
            host=app.config['DB_HOST'],
            port=app.config['DB_PORT'],
            database=app.config['DB_NAME'],
            user=app.config['DB_USER'],
            password=app.config['DB_PASSWORD'],
            cursor_factory=RealDictCursor
        )
        return conn
    except psycopg2.OperationalError as e:
        app.logger.error(f"Failed to connect to database: {e}")
        raise

def validate_product_data(data):
    """Валидация данных продукта"""
    errors = []
    
    if not data.get('article'):
        errors.append("Артикул не может быть пустым")
    elif len(data['article']) > 50:
        errors.append("Артикул не может быть длиннее 50 символов")
    
    if not data.get('name'):
        errors.append("Наименование не может быть пустым")
    elif len(data['name']) > 200:
        errors.append("Наименование не может быть длиннее 200 символов")
    
    if not data.get('product_type_id'):
        errors.append("Необходимо выбрать тип продукции")
    
    if not data.get('material_type_id'):
        errors.append("Необходимо выбрать основной материал")
    
    try:
        price = float(data.get('min_price', 0))
        if price < 0:
            errors.append("Стоимость не может быть отрицательной")
        elif price == 0:
            errors.append("Стоимость должна быть больше 0")
        else:
            data['min_price'] = round(price, 2)
    except (ValueError, TypeError):
        errors.append("Стоимость должна быть числом")
    
    return errors

def calculate_total_hours(product_id):
    """
    Алгоритм расчета времени изготовления продукции
    Время складывается из времени нахождения в каждом цехе
    Возвращает целое неотрицательное число (округление вверх)
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT COALESCE(SUM(hours), 0) as total
            FROM product_workshops
            WHERE product_id = %s
        """, (product_id,))
        
        result = cur.fetchone()
        total = float(result['total']) if result and result['total'] else 0
        
        return math.ceil(total) if total > 0 else 0
    
    except Exception as e:
        app.logger.error(f"Error calculating total hours for product {product_id}: {e}")
        return 0
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

@app.route('/')
@handle_db_errors
def index():
    """Главная страница"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM products")
        products_count = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) FROM workshops")
        workshops_count = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) FROM material_types")
        material_types_count = cur.fetchone()['count']
        
        cur.execute("SELECT COUNT(*) FROM product_types")
        product_types_count = cur.fetchone()['count']
        
        cur.execute("""
            SELECT p.*, pt.name as product_type_name, mt.name as material_name, mt.loss_percentage
            FROM products p
            JOIN product_types pt ON p.product_type_id = pt.id
            JOIN material_types mt ON p.material_type_id = mt.id
            ORDER BY p.id DESC
            LIMIT 5
        """)
        latest_products = cur.fetchall()
        
        for product in latest_products:
            product['total_hours'] = calculate_total_hours(product['id'])
        
        return render_template('index.html', 
                             products_count=products_count,
                             workshops_count=workshops_count,
                             material_types_count=material_types_count,
                             product_types_count=product_types_count,
                             latest_products=latest_products)
    
    except Exception as e:
        app.logger.error(f"Error in index route: {traceback.format_exc()}")
        flash('Произошла ошибка при загрузке главной страницы', 'error')
        return render_template('index.html', 
                             products_count=0,
                             workshops_count=0,
                             material_types_count=0,
                             product_types_count=0,
                             latest_products=[])
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/products')
@handle_db_errors
def products():
    """Список продукции"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT p.*, pt.name as product_type_name, mt.name as material_name, 
                   mt.loss_percentage,
                   (SELECT COUNT(*) FROM product_workshops WHERE product_id = p.id) as workshops_count
            FROM products p
            JOIN product_types pt ON p.product_type_id = pt.id
            JOIN material_types mt ON p.material_type_id = mt.id
            ORDER BY p.id
        """)
        products = cur.fetchall()
        
        for product in products:
            product['total_hours'] = calculate_total_hours(product['id'])
        
        return render_template('products.html', products=products)
    
    except Exception as e:
        app.logger.error(f"Error in products route: {traceback.format_exc()}")
        flash('Ошибка при загрузке списка продукции', 'error')
        return render_template('products.html', products=[])
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/products/<int:id>')
@handle_db_errors
def product_detail(id):
    """Детальная информация о продукте"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT p.*, pt.name as product_type_name, pt.coefficient,
                   mt.name as material_name, mt.loss_percentage
            FROM products p
            JOIN product_types pt ON p.product_type_id = pt.id
            JOIN material_types mt ON p.material_type_id = mt.id
            WHERE p.id = %s
        """, (id,))
        product = cur.fetchone()
        
        if not product:
            flash(f'Продукт с ID {id} не найден', 'warning')
            return redirect(url_for('products'))
        
        cur.execute("""
            SELECT w.*, pw.hours
            FROM workshops w
            JOIN product_workshops pw ON w.id = pw.workshop_id
            WHERE pw.product_id = %s
            ORDER BY w.workshop_type, w.name
        """, (id,))
        workshops = cur.fetchall()
        
        total_hours = calculate_total_hours(id)
        workshops_count = len(workshops)
        
        return render_template('product_detail.html',
                             product=product,
                             workshops=workshops,
                             total_hours=total_hours,
                             workshops_count=workshops_count)
    
    except Exception as e:
        app.logger.error(f"Error in product_detail route for id {id}: {traceback.format_exc()}")
        flash('Ошибка при загрузке информации о продукте', 'error')
        return redirect(url_for('products'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/products/add', methods=['GET', 'POST'])
@handle_db_errors
def add_product():
    """Добавление нового продукта"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT id, name FROM product_types ORDER BY name")
        product_types = cur.fetchall()
        
        cur.execute("SELECT id, name FROM material_types ORDER BY name")
        material_types = cur.fetchall()
        
    except Exception as e:
        app.logger.error(f"Error loading form data: {traceback.format_exc()}")
        flash('Ошибка при загрузке данных для формы', 'error')
        return redirect(url_for('products'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    
    if request.method == 'POST':
        form_data = {
            'article': request.form.get('article', '').strip(),
            'name': request.form.get('name', '').strip(),
            'product_type_id': request.form.get('product_type_id'),
            'material_type_id': request.form.get('material_type_id'),
            'min_price': request.form.get('min_price', '0')
        }
        
        errors = validate_product_data(form_data)
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('product_edit.html', 
                                 product=form_data,
                                 product_types=product_types,
                                 material_types=material_types,
                                 is_editing=False)
        
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO products (product_type_id, name, article, min_price, material_type_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                form_data['product_type_id'],
                form_data['name'],
                form_data['article'],
                form_data['min_price'],
                form_data['material_type_id']
            ))
            product_id = cur.fetchone()['id']
            conn.commit()
            
            flash(f'Продукт "{form_data["name"]}" успешно добавлен', 'success')
            return redirect(url_for('product_detail', id=product_id))
            
        except pg_errors.UniqueViolation:
            conn.rollback()
            flash('Продукт с таким артикулом уже существует', 'error')
            return render_template('product_edit.html', 
                                 product=form_data,
                                 product_types=product_types,
                                 material_types=material_types,
                                 is_editing=False)
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error adding product: {traceback.format_exc()}")
            flash(f'Ошибка при добавлении продукта: {str(e)}', 'error')
            return render_template('product_edit.html', 
                                 product=form_data,
                                 product_types=product_types,
                                 material_types=material_types,
                                 is_editing=False)
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
    
    return render_template('product_edit.html', 
                         product=None,
                         product_types=product_types,
                         material_types=material_types,
                         is_editing=False)

@app.route('/products/edit/<int:id>', methods=['GET', 'POST'])
@handle_db_errors
def edit_product(id):
    """Редактирование продукта"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT id, name FROM product_types ORDER BY name")
        product_types = cur.fetchall()
        
        cur.execute("SELECT id, name FROM material_types ORDER BY name")
        material_types = cur.fetchall()
        
    except Exception as e:
        app.logger.error(f"Error loading form data: {traceback.format_exc()}")
        flash('Ошибка при загрузке данных для формы', 'error')
        return redirect(url_for('products'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    
    if request.method == 'POST':
        form_data = {
            'id': id,
            'article': request.form.get('article', '').strip(),
            'name': request.form.get('name', '').strip(),
            'product_type_id': request.form.get('product_type_id'),
            'material_type_id': request.form.get('material_type_id'),
            'min_price': request.form.get('min_price', '0')
        }
        
        errors = validate_product_data(form_data)
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('product_edit.html', 
                                 product=form_data,
                                 product_types=product_types,
                                 material_types=material_types,
                                 is_editing=True)
        
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("SELECT id FROM products WHERE id = %s", (id,))
            if not cur.fetchone():
                flash(f'Продукт с ID {id} не найден', 'error')
                return redirect(url_for('products'))
            
            cur.execute("""
                UPDATE products 
                SET product_type_id = %s, name = %s, article = %s, 
                    min_price = %s, material_type_id = %s
                WHERE id = %s
            """, (
                form_data['product_type_id'],
                form_data['name'],
                form_data['article'],
                form_data['min_price'],
                form_data['material_type_id'],
                id
            ))
            conn.commit()
            
            flash(f'Продукт "{form_data["name"]}" успешно обновлен', 'success')
            return redirect(url_for('product_detail', id=id))
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error updating product {id}: {traceback.format_exc()}")
            flash(f'Ошибка при обновлении продукта: {str(e)}', 'error')
            return render_template('product_edit.html', 
                                 product=form_data,
                                 product_types=product_types,
                                 material_types=material_types,
                                 is_editing=True)
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
    
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT p.*, pt.name as product_type_name, mt.name as material_name
            FROM products p
            JOIN product_types pt ON p.product_type_id = pt.id
            JOIN material_types mt ON p.material_type_id = mt.id
            WHERE p.id = %s
        """, (id,))
        product = cur.fetchone()
        
        if not product:
            flash(f'Продукт с ID {id} не найден', 'warning')
            return redirect(url_for('products'))
        
        return render_template('product_edit.html', 
                             product=product,
                             product_types=product_types,
                             material_types=material_types,
                             is_editing=True)
    
    except Exception as e:
        app.logger.error(f"Error loading product {id} for edit: {traceback.format_exc()}")
        flash('Ошибка при загрузке данных продукта', 'error')
        return redirect(url_for('products'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/products/delete/<int:id>', methods=['POST'])
@handle_db_errors
def delete_product(id):
    """Удаление продукта"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT name FROM products WHERE id = %s", (id,))
        product = cur.fetchone()
        
        if not product:
            flash(f'Продукт с ID {id} не найден', 'error')
            return redirect(url_for('products'))
        
        cur.execute("SELECT COUNT(*) FROM product_workshops WHERE product_id = %s", (id,))
        workshops_count = cur.fetchone()['count']
        
        if workshops_count > 0:
            cur.execute("DELETE FROM product_workshops WHERE product_id = %s", (id,))
        
        cur.execute("DELETE FROM products WHERE id = %s", (id,))
        conn.commit()
        
        flash(f'Продукт "{product["name"]}" успешно удален', 'success')
        
    except Exception as e:
        conn.rollback()
        app.logger.error(f"Error deleting product {id}: {traceback.format_exc()}")
        flash(f'Ошибка при удалении продукта: {str(e)}', 'error')
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    
    return redirect(url_for('products'))

@app.route('/workshops')
@handle_db_errors
def workshops():
    """Список цехов"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT w.*, 
                   (SELECT COUNT(*) FROM product_workshops WHERE workshop_id = w.id) as products_count
            FROM workshops w
            ORDER BY w.workshop_type, w.name
        """)
        workshops = cur.fetchall()
        
        return render_template('workshops.html', workshops=workshops)
    
    except Exception as e:
        app.logger.error(f"Error in workshops route: {traceback.format_exc()}")
        flash('Ошибка при загрузке списка цехов', 'error')
        return render_template('workshops.html', workshops=[])
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/workshops/<int:id>')
@handle_db_errors
def workshop_detail(id):
    """Детальная информация о цехе"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM workshops WHERE id = %s
        """, (id,))
        workshop = cur.fetchone()
        
        if not workshop:
            flash(f'Цех с ID {id} не найден', 'warning')
            return redirect(url_for('workshops'))
        
        cur.execute("""
            SELECT p.*, pt.name as product_type_name, pw.hours,
                   (SELECT SUM(hours) FROM product_workshops WHERE product_id = p.id) as total_hours
            FROM products p
            JOIN product_workshops pw ON p.id = pw.product_id
            JOIN product_types pt ON p.product_type_id = pt.id
            WHERE pw.workshop_id = %s
            ORDER BY p.name
        """, (id,))
        products = cur.fetchall()
        
        total_hours = sum(p['hours'] for p in products) if products else 0
        avg_hours = total_hours / len(products) if products else 0
        
        return render_template('workshop_detail.html',
                             workshop=workshop,
                             products=products,
                             total_hours=total_hours,
                             avg_hours=avg_hours)
    
    except Exception as e:
        app.logger.error(f"Error in workshop_detail route: {traceback.format_exc()}")
        flash('Ошибка при загрузке информации о цехе', 'error')
        return redirect(url_for('workshops'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/products/<int:product_id>/workshops', methods=['GET', 'POST'])
@handle_db_errors
def product_workshops(product_id):
    """Управление цехами для продукта"""
    conn = None
    cur = None
    
    if request.method == 'POST':
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("SELECT name FROM products WHERE id = %s", (product_id,))
            product = cur.fetchone()
            
            if not product:
                flash(f'Продукт с ID {product_id} не найден', 'error')
                return redirect(url_for('products'))
            
            cur.execute("DELETE FROM product_workshops WHERE product_id = %s", (product_id,))
            
            added_count = 0
            for key, value in request.form.items():
                if key.startswith('hours_'):
                    workshop_id = key.replace('hours_', '')
                    try:
                        hours = float(value)
                        if hours > 0:
                            cur.execute("""
                                INSERT INTO product_workshops (product_id, workshop_id, hours)
                                VALUES (%s, %s, %s)
                            """, (product_id, workshop_id, hours))
                            added_count += 1
                    except (ValueError, TypeError):
                        flash(f'Некорректное значение времени для цеха {workshop_id}', 'warning')
            
            conn.commit()
            
            if added_count > 0:
                flash(f'Данные для продукта "{product["name"]}" успешно обновлены. Добавлено {added_count} цехов.', 'success')
            else:
                flash('Не добавлено ни одного цеха. Укажите время для хотя бы одного цеха.', 'warning')
            
            return redirect(url_for('product_detail', id=product_id))
            
        except Exception as e:
            conn.rollback()
            app.logger.error(f"Error updating workshops for product {product_id}: {traceback.format_exc()}")
            flash(f'Ошибка при обновлении данных: {str(e)}', 'error')
            return redirect(url_for('product_workshops', product_id=product_id))
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT p.*, pt.name as product_type_name, mt.name as material_name
            FROM products p
            JOIN product_types pt ON p.product_type_id = pt.id
            JOIN material_types mt ON p.material_type_id = mt.id
            WHERE p.id = %s
        """, (product_id,))
        product = cur.fetchone()
        
        if not product:
            flash(f'Продукт с ID {product_id} не найден', 'warning')
            return redirect(url_for('products'))
        
        cur.execute("""
            SELECT w.*, pw.hours
            FROM workshops w
            LEFT JOIN product_workshops pw ON w.id = pw.workshop_id AND pw.product_id = %s
            ORDER BY w.workshop_type, w.name
        """, (product_id,))
        workshops = cur.fetchall()
        
        return render_template('product_workshops.html', 
                             product=product,
                             workshops=workshops)
    
    except Exception as e:
        app.logger.error(f"Error loading workshops for product {product_id}: {traceback.format_exc()}")
        flash('Ошибка при загрузке данных', 'error')
        return redirect(url_for('products'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/calculator', methods=['GET'])
@handle_db_errors
def material_calculator_page():
    """Страница калькулятора сырья"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT id, name FROM product_types ORDER BY name")
        product_types = cur.fetchall()
        
        cur.execute("SELECT id, name FROM material_types ORDER BY name")
        material_types = cur.fetchall()
        
        return render_template('material_calculator.html',
                             product_types=product_types,
                             material_types=material_types,
                             result=None,
                             product=None)
    
    except Exception as e:
        app.logger.error(f"Error loading calculator page: {traceback.format_exc()}")
        flash('Ошибка при загрузке калькулятора', 'error')
        return redirect(url_for('index'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/calculator/product/<int:product_id>', methods=['GET'])
@handle_db_errors
def material_calculator_for_product(product_id):
    """Калькулятор сырья для конкретного продукта"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT p.*, pt.name as product_type_name, mt.name as material_name
            FROM products p
            JOIN product_types pt ON p.product_type_id = pt.id
            JOIN material_types mt ON p.material_type_id = mt.id
            WHERE p.id = %s
        """, (product_id,))
        product = cur.fetchone()
        
        if not product:
            flash(f'Продукт с ID {product_id} не найден', 'warning')
            return redirect(url_for('products'))
        
        return render_template('material_calculator.html',
                             product_types=[],
                             material_types=[],
                             product=product,
                             result=None)
    
    except Exception as e:
        app.logger.error(f"Error loading calculator for product: {traceback.format_exc()}")
        flash('Ошибка при загрузке калькулятора', 'error')
        return redirect(url_for('products'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/calculate', methods=['POST'])
@handle_db_errors
def calculate_material():
    """Обработка расчета сырья"""
    conn = None
    cur = None
    
    try:
        quantity = int(request.form.get('quantity', 1))
        length = float(request.form.get('length', 0))
        width = float(request.form.get('width', 0))
        
        if quantity <= 0 or length <= 0 or width <= 0:
            flash('Все параметры должны быть положительными числами', 'error')
            return redirect(url_for('material_calculator_page'))
        
        if 'product_id' in request.form and request.form['product_id']:
            product_id = int(request.form['product_id'])
            
            result = material_calculator.calculate_for_product(
                product_id, quantity, length, width
            )
            
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT p.*, pt.name as product_type_name, mt.name as material_name,
                       pt.coefficient, mt.loss_percentage
                FROM products p
                JOIN product_types pt ON p.product_type_id = pt.id
                JOIN material_types mt ON p.material_type_id = mt.id
                WHERE p.id = %s
            """, (product_id,))
            product_data = cur.fetchone()
            
            if not product_data:
                flash('Продукт не найден', 'error')
                return redirect(url_for('products'))
            
            product_coef = float(product_data['coefficient'])
            loss_percent = float(product_data['loss_percentage'])
            
            area = length * width
            material_per_unit = area * product_coef
            total_without_loss = material_per_unit * quantity
            total_with_loss = total_without_loss * (1 + loss_percent)
            
            cur.execute("SELECT id, name FROM product_types ORDER BY name")
            product_types = cur.fetchall()
            
            cur.execute("SELECT id, name FROM material_types ORDER BY name")
            material_types = cur.fetchall()
            
            cur.close()
            conn.close()
            
            if result > 0:
                return render_template('material_calculator.html',
                                     product=product_data,
                                     product_types=product_types,
                                     material_types=material_types,
                                     result=result,
                                     quantity=quantity,
                                     length=length,
                                     width=width,
                                     material_per_unit=material_per_unit,
                                     total_without_loss=total_without_loss,
                                     total_with_loss=total_with_loss,
                                     loss_percentage=loss_percent,
                                     product_type_name=product_data['product_type_name'],
                                     material_type_name=product_data['material_name'])
            else:
                return render_template('material_calculator.html',
                                     product=product_data,
                                     product_types=product_types,
                                     material_types=material_types,
                                     result=-1,
                                     error_message="Ошибка расчета. Проверьте параметры.")
        
        else:
            product_type_id = int(request.form.get('product_type_id', 0))
            material_type_id = int(request.form.get('material_type_id', 0))
            
            if product_type_id == 0 or material_type_id == 0:
                flash('Необходимо выбрать тип продукции и тип материала', 'error')
                return redirect(url_for('material_calculator_page'))
            
            result = material_calculator.calculate_raw_material(
                product_type_id, material_type_id, quantity, length, width
            )
            
            conn = get_db_connection()
            cur = conn.cursor()
            
            cur.execute("SELECT id, name FROM product_types ORDER BY name")
            product_types = cur.fetchall()
            
            cur.execute("SELECT id, name FROM material_types ORDER BY name")
            material_types = cur.fetchall()
            
            cur.execute("SELECT name, coefficient FROM product_types WHERE id = %s", (product_type_id,))
            product_data = cur.fetchone()
            product_type_name = product_data['name'] if product_data else "Неизвестный тип"
            product_coef = float(product_data['coefficient']) if product_data else 1.0
            
            cur.execute("SELECT name, loss_percentage FROM material_types WHERE id = %s", (material_type_id,))
            material_data = cur.fetchone()
            material_type_name = material_data['name'] if material_data else "Неизвестный материал"
            loss_percent = float(material_data['loss_percentage']) if material_data else 0.0
            
            cur.close()
            conn.close()
            
            if result > 0:
                area = length * width
                material_per_unit = area * product_coef
                total_without_loss = material_per_unit * quantity
                total_with_loss = total_without_loss * (1 + loss_percent)
                
                return render_template('material_calculator.html',
                                     product_types=product_types,
                                     material_types=material_types,
                                     result=result,
                                     quantity=quantity,
                                     length=length,
                                     width=width,
                                     material_per_unit=material_per_unit,
                                     total_without_loss=total_without_loss,
                                     total_with_loss=total_with_loss,
                                     loss_percentage=loss_percent,
                                     product_type_name=product_type_name,
                                     material_type_name=material_type_name,
                                     product=None)
            else:
                return render_template('material_calculator.html',
                                     product_types=product_types,
                                     material_types=material_types,
                                     result=-1,
                                     error_message="Ошибка расчета. Проверьте параметры.",
                                     product=None)
    
    except Exception as e:
        app.logger.error(f"Error in calculate_material: {traceback.format_exc()}")
        flash(f'Ошибка при расчете: {str(e)}', 'error')
        return redirect(url_for('material_calculator_page'))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.errorhandler(404)
def page_not_found(e):
    """Обработка ошибки 404"""
    return render_template('error.html',
                         error_title="Страница не найдена",
                         error_message="Запрашиваемая страница не существует. Проверьте правильность URL.",
                         back_url=url_for('index')), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Обработка ошибки 500"""
    app.logger.error(f"Internal server error: {traceback.format_exc()}")
    return render_template('error.html',
                         error_title="Внутренняя ошибка сервера",
                         error_message="Произошла внутренняя ошибка сервера. Наша команда уже работает над ее устранением.",
                         back_url=url_for('index')), 500

if __name__ == '__main__':
    app.run(debug=True)