from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config
import math

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

def get_db_connection():
    conn = psycopg2.connect(
        host=app.config['DB_HOST'],
        port=app.config['DB_PORT'],
        database=app.config['DB_NAME'],
        user=app.config['DB_USER'],
        password=app.config['DB_PASSWORD'],
        cursor_factory=RealDictCursor
    )
    return conn

def calculate_total_hours(product_id):
    """
    Алгоритм расчета времени изготовления продукции
    Время складывается из времени нахождения в каждом цехе
    Возвращает целое неотрицательное число (округление вверх)
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Получаем все цеха для данного продукта
        cur.execute("""
            SELECT SUM(hours) as total
            FROM product_workshops
            WHERE product_id = %s
        """, (product_id,))
        
        result = cur.fetchone()
        total = result['total'] if result and result['total'] else 0
        
        # Округляем до целого числа (вверх, если есть дробная часть)
        return math.ceil(float(total)) if total else 0
    
    except Exception as e:
        print(f"Ошибка при расчете времени: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Получаем статистику
    cur.execute("SELECT COUNT(*) FROM products")
    products_count = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) FROM workshops")
    workshops_count = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) FROM material_types")
    material_types_count = cur.fetchone()['count']
    
    cur.execute("SELECT COUNT(*) FROM product_types")
    product_types_count = cur.fetchone()['count']
    
    # Получаем последние 5 продуктов с расчетом времени
    cur.execute("""
        SELECT p.*, pt.name as product_type_name, mt.name as material_name, mt.loss_percentage
        FROM products p
        JOIN product_types pt ON p.product_type_id = pt.id
        JOIN material_types mt ON p.material_type_id = mt.id
        ORDER BY p.id DESC
        LIMIT 5
    """)
    latest_products = cur.fetchall()
    
    # Рассчитываем время для каждого продукта
    for product in latest_products:
        product['total_hours'] = calculate_total_hours(product['id'])
    
    cur.close()
    conn.close()
    
    return render_template('index.html', 
                         products_count=products_count,
                         workshops_count=workshops_count,
                         material_types_count=material_types_count,
                         product_types_count=product_types_count,
                         latest_products=latest_products)

@app.route('/products')
def products():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Получаем все продукты с дополнительной информацией
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
    
    # Рассчитываем время для каждого продукта
    for product in products:
        product['total_hours'] = calculate_total_hours(product['id'])
    
    cur.close()
    conn.close()
    
    return render_template('products.html', products=products)

@app.route('/products/<int:id>')
def product_detail(id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Получаем информацию о продукте
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
        flash('Продукт не найден', 'danger')
        return redirect(url_for('products'))
    
    # Получаем цеха для этого продукта
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
    
    cur.close()
    conn.close()
    
    return render_template('product_detail.html',
                         product=product,
                         workshops=workshops,
                         total_hours=total_hours,
                         workshops_count=workshops_count)

@app.route('/products/add', methods=['GET', 'POST'])
def add_product():
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            cur.execute("""
                INSERT INTO products (product_type_id, name, article, min_price, material_type_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                request.form['product_type_id'],
                request.form['name'],
                request.form['article'],
                request.form['min_price'],
                request.form['material_type_id']
            ))
            product_id = cur.fetchone()['id']
            conn.commit()
            flash('Продукт успешно добавлен', 'success')
            return redirect(url_for('product_detail', id=product_id))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при добавлении: {str(e)}', 'danger')
    
    # Получаем данные для выпадающих списков
    cur.execute("SELECT id, name FROM product_types ORDER BY name")
    product_types = cur.fetchall()
    
    cur.execute("SELECT id, name FROM material_types ORDER BY name")
    material_types = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('product_edit.html', 
                         product=None,
                         product_types=product_types,
                         material_types=material_types)

@app.route('/products/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            cur.execute("""
                UPDATE products 
                SET product_type_id = %s, name = %s, article = %s, 
                    min_price = %s, material_type_id = %s
                WHERE id = %s
            """, (
                request.form['product_type_id'],
                request.form['name'],
                request.form['article'],
                request.form['min_price'],
                request.form['material_type_id'],
                id
            ))
            conn.commit()
            flash('Продукт успешно обновлен', 'success')
            return redirect(url_for('product_detail', id=id))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при обновлении: {str(e)}', 'danger')
    
    # Получаем данные продукта
    cur.execute("""
        SELECT p.*, pt.name as product_type_name, mt.name as material_name
        FROM products p
        JOIN product_types pt ON p.product_type_id = pt.id
        JOIN material_types mt ON p.material_type_id = mt.id
        WHERE p.id = %s
    """, (id,))
    product = cur.fetchone()
    
    if not product:
        flash('Продукт не найден', 'danger')
        return redirect(url_for('products'))
    
    # Получаем данные для выпадающих списков
    cur.execute("SELECT id, name FROM product_types ORDER BY name")
    product_types = cur.fetchall()
    
    cur.execute("SELECT id, name FROM material_types ORDER BY name")
    material_types = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('product_edit.html', 
                         product=product,
                         product_types=product_types,
                         material_types=material_types)

@app.route('/products/delete/<int:id>', methods=['POST'])
def delete_product(id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("DELETE FROM products WHERE id = %s", (id,))
        conn.commit()
        flash('Продукт успешно удален', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('products'))

@app.route('/workshops')
def workshops():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT w.*, 
               (SELECT COUNT(*) FROM product_workshops WHERE workshop_id = w.id) as products_count
        FROM workshops w
        ORDER BY w.workshop_type, w.name
    """)
    workshops = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('workshops.html', workshops=workshops)

@app.route('/products/<int:product_id>/workshops', methods=['GET', 'POST'])
def product_workshops(product_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            # Удаляем старые связи
            cur.execute("DELETE FROM product_workshops WHERE product_id = %s", (product_id,))
            
            # Добавляем новые
            for key, value in request.form.items():
                if key.startswith('hours_'):
                    workshop_id = key.replace('hours_', '')
                    hours = float(value)
                    if hours > 0:
                        cur.execute("""
                            INSERT INTO product_workshops (product_id, workshop_id, hours)
                            VALUES (%s, %s, %s)
                        """, (product_id, workshop_id, hours))
            
            conn.commit()
            flash('Данные успешно обновлены', 'success')
            return redirect(url_for('product_detail', id=product_id))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при обновлении: {str(e)}', 'danger')
    
    # Информация о продукте
    cur.execute("""
        SELECT p.*, pt.name as product_type_name, mt.name as material_name
        FROM products p
        JOIN product_types pt ON p.product_type_id = pt.id
        JOIN material_types mt ON p.material_type_id = mt.id
        WHERE p.id = %s
    """, (product_id,))
    product = cur.fetchone()
    
    if not product:
        flash('Продукт не найден', 'danger')
        return redirect(url_for('products'))
    
    # Все цеха с указанием времени изготовления
    cur.execute("""
        SELECT w.*, pw.hours
        FROM workshops w
        LEFT JOIN product_workshops pw ON w.id = pw.workshop_id AND pw.product_id = %s
        ORDER BY w.workshop_type, w.name
    """, (product_id,))
    workshops = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('product_workshops.html', 
                         product=product,
                         workshops=workshops)

if __name__ == '__main__':
    app.run(debug=True)