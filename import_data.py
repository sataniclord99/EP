import openpyxl
import psycopg2
from config import Config

def read_excel_file(filepath, sheet_index=0):
    """Чтение Excel файла с правильной обработкой заголовков"""
    print(f"Чтение файла: {filepath}")
    workbook = openpyxl.load_workbook(filepath, data_only=True)
    sheet = workbook.worksheets[sheet_index]
    
    # Получаем заголовки из первой строки и очищаем их от лишних пробелов
    headers = []
    for cell in sheet[1]:
        if cell.value:
            # Удаляем лишние пробелы и символы
            header = str(cell.value).strip()
            headers.append(header)
            print(f"Найден заголовок: '{header}'")
    
    print(f"Всего заголовков: {len(headers)}")
    
    # Читаем данные со второй строки
    data = []
    for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
        if any(cell is not None for cell in row):  # Пропускаем пустые строки
            row_data = {}
            for i, value in enumerate(row):
                if i < len(headers):
                    # Преобразуем значение в строку, если это необходимо
                    if value is not None:
                        if isinstance(value, (int, float)):
                            value = str(value).replace(',', '.')
                        row_data[headers[i]] = value
                    else:
                        row_data[headers[i]] = None
            data.append(row_data)
            print(f"Строка {row_idx}: {row_data}")
    
    print(f"Прочитано {len(data)} строк данных\n")
    return data

def import_material_types(conn, filepath):
    """Импорт типов материалов"""
    print("Импорт типов материалов...")
    data = read_excel_file(filepath)
    cur = conn.cursor()
    
    count = 0
    for row in data:
        try:
            material_name = row.get('Тип материала')
            loss = row.get('Процент потерь сырья')
            
            if material_name and loss is not None:
                cur.execute("""
                    INSERT INTO material_types (name, loss_percentage)
                    VALUES (%s, %s)
                    ON CONFLICT (name) DO NOTHING
                """, (material_name, float(loss)))
                count += 1
                print(f"  Добавлен материал: {material_name}")
        except Exception as e:
            print(f"  Ошибка при импорте материала: {e}")
            print(f"  Данные: {row}")
    
    conn.commit()
    print(f"Импортировано {count} типов материалов\n")

def import_product_types(conn, filepath):
    """Импорт типов продукции"""
    print("Импорт типов продукции...")
    data = read_excel_file(filepath)
    cur = conn.cursor()
    
    count = 0
    for row in data:
        try:
            product_type = row.get('Тип продукции')
            coefficient = row.get('Коэффициент типа продукции')
            
            if product_type and coefficient is not None:
                cur.execute("""
                    INSERT INTO product_types (name, coefficient)
                    VALUES (%s, %s)
                    ON CONFLICT (name) DO NOTHING
                """, (product_type, float(coefficient)))
                count += 1
                print(f"  Добавлен тип продукции: {product_type}")
        except Exception as e:
            print(f"  Ошибка при импорте типа продукции: {e}")
            print(f"  Данные: {row}")
    
    conn.commit()
    print(f"Импортировано {count} типов продукции\n")

def import_workshops(conn, filepath):
    """Импорт цехов"""
    print("Импорт цехов...")
    data = read_excel_file(filepath)
    cur = conn.cursor()
    
    # Сначала посмотрим, какие ключи есть в данных
    if data:
        print(f"Доступные ключи в первой записи: {list(data[0].keys())}")
    
    count = 0
    for row in data:
        try:
            # Пробуем разные варианты названий столбцов
            workshop_name = row.get('Название цеха') or row.get('Название цеха')
            workshop_type = row.get('Тип цеха')
            
            # Пробуем разные варианты для количества человек
            employee_count = None
            for key in row.keys():
                if 'человек' in key.lower() or 'количество' in key.lower():
                    employee_count = row.get(key)
                    print(f"  Найдено поле для количества: '{key}' = {employee_count}")
                    break
            
            if workshop_name and workshop_type and employee_count is not None:
                # Преобразуем employee_count в число
                if isinstance(employee_count, str):
                    employee_count = employee_count.replace(',', '.').strip()
                employee_count = float(employee_count)
                
                cur.execute("""
                    INSERT INTO workshops (name, workshop_type, employee_count)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        workshop_type = EXCLUDED.workshop_type,
                        employee_count = EXCLUDED.employee_count
                """, (workshop_name, workshop_type, int(employee_count)))
                count += 1
                print(f"  Добавлен цех: {workshop_name}, тип: {workshop_type}, сотрудников: {employee_count}")
            else:
                print(f"  Пропущена строка: недостаточно данных")
                print(f"    Название цеха: {workshop_name}")
                print(f"    Тип цеха: {workshop_type}")
                print(f"    Кол-во человек: {employee_count}")
                
        except Exception as e:
            print(f"  Ошибка при импорте цеха: {e}")
            print(f"  Данные: {row}")
    
    conn.commit()
    print(f"Импортировано {count} цехов\n")

def import_products(conn, filepath):
    """Импорт продукции"""
    print("Импорт продукции...")
    data = read_excel_file(filepath)
    cur = conn.cursor()
    
    # Получаем справочные данные
    cur.execute("SELECT id, name FROM product_types")
    product_types = {row[1].strip() if row[1] else '': row[0] for row in cur.fetchall()}
    print(f"Найдено типов продукции: {product_types}")
    
    cur.execute("SELECT id, name FROM material_types")
    material_types = {row[1].strip() if row[1] else '': row[0] for row in cur.fetchall()}
    print(f"Найдено типов материалов: {material_types}")
    
    count = 0
    errors = []
    
    for row in data:
        try:
            product_type_name = row.get('Тип продукции')
            product_name = row.get('Наименование продукции')
            article = row.get('Артикул')
            min_price = row.get('Минимальная стоимость для партнера')
            material_name = row.get('Основной материал')
            
            if all([product_type_name, product_name, article, min_price, material_name]):
                product_type_id = product_types.get(product_type_name.strip())
                material_type_id = material_types.get(material_name.strip())
                
                if product_type_id and material_type_id:
                    cur.execute("""
                        INSERT INTO products (product_type_id, name, article, min_price, material_type_id)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (article) DO UPDATE SET
                            product_type_id = EXCLUDED.product_type_id,
                            name = EXCLUDED.name,
                            min_price = EXCLUDED.min_price,
                            material_type_id = EXCLUDED.material_type_id
                    """, (
                        product_type_id,
                        product_name,
                        str(article),
                        float(min_price),
                        material_type_id
                    ))
                    count += 1
                    print(f"  Добавлен продукт: {product_name}")
                else:
                    errors.append(f"Не найдены типы: продукт '{product_name}', тип продукции ID: {product_type_id}, материал ID: {material_type_id}")
        except Exception as e:
            errors.append(f"Ошибка при импорте {row.get('Наименование продукции', 'Unknown')}: {e}")
    
    conn.commit()
    
    if errors:
        print("\nОшибки при импорте продуктов:")
        for error in errors[:5]:  # Покажем первые 5 ошибок
            print(f"  {error}")
    
    print(f"Импортировано {count} продуктов\n")

def import_product_workshops(conn, filepath):
    """Импорт связей продукции с цехами"""
    print("Импорт связей продукция-цеха...")
    data = read_excel_file(filepath)
    cur = conn.cursor()
    
    # Получаем справочные данные
    cur.execute("SELECT id, name FROM products")
    products = {}
    for row in cur.fetchall():
        products[row[1].strip()] = row[0]
    print(f"Найдено продуктов: {len(products)}")
    
    cur.execute("SELECT id, name FROM workshops")
    workshops = {}
    for row in cur.fetchall():
        workshops[row[1].strip()] = row[0]
    print(f"Найдено цехов: {len(workshops)}")
    
    count = 0
    errors = []
    
    for row in data:
        try:
            product_name = row.get('Наименование продукции')
            workshop_name = row.get('Название цеха')
            hours = row.get('Время изготовления, ч')
            
            if product_name and workshop_name and hours is not None:
                product_id = products.get(product_name.strip())
                workshop_id = workshops.get(workshop_name.strip())
                
                if product_id and workshop_id:
                    # Преобразуем часы в число
                    if isinstance(hours, str):
                        hours = hours.replace(',', '.').strip()
                    hours = float(hours)
                    
                    cur.execute("""
                        INSERT INTO product_workshops (product_id, workshop_id, hours)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (product_id, workshop_id) DO UPDATE SET
                            hours = EXCLUDED.hours
                    """, (product_id, workshop_id, hours))
                    count += 1
                    print(f"  Добавлена связь: {product_name} -> {workshop_name} ({hours} ч)")
                else:
                    if not product_id:
                        errors.append(f"Продукт не найден: '{product_name}'")
                    if not workshop_id:
                        errors.append(f"Цех не найден: '{workshop_name}'")
        except Exception as e:
            errors.append(f"Ошибка при импорте связи: {e}")
    
    conn.commit()
    
    if errors:
        print("\nОшибки при импорте связей:")
        for error in errors[:10]:  # Покажем первые 10 ошибок
            print(f"  {error}")
    
    print(f"Импортировано {count} связей продукция-цех\n")

def check_excel_file_structure(filepath):
    """Проверка структуры Excel файла"""
    try:
        workbook = openpyxl.load_workbook(filepath, data_only=True)
        sheet = workbook.active
        
        print(f"\n=== Проверка файла: {filepath} ===")
        print(f"Листов: {len(workbook.sheetnames)}")
        print(f"Активный лист: {sheet.title}")
        
        # Заголовки
        headers = []
        for cell in sheet[1]:
            if cell.value:
                headers.append(str(cell.value))
        print(f"Заголовки: {headers}")
        
        # Первые 3 строки данных
        print("\nПервые 3 строки данных:")
        for i, row in enumerate(sheet.iter_rows(min_row=2, max_row=5, values_only=True), 2):
            if any(cell is not None for cell in row):
                print(f"  Строка {i}: {row}")
        
        print("=" * 50)
        return True
    except Exception as e:
        print(f"Ошибка при проверке файла {filepath}: {e}")
        return False

def main():
    # Проверяем наличие необходимых библиотек
    try:
        import openpyxl
        print("✓ openpyxl загружен")
    except ImportError as e:
        print("✗ Ошибка: openpyxl не установлен")
        print("  Установите: pip install openpyxl==3.1.2")
        return
    
    # Подключение к БД
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        print("✓ Подключение к БД успешно")
    except Exception as e:
        print(f"✗ Ошибка подключения к БД: {e}")
        print("  Проверьте параметры в config.py")
        return
    
    try:
        print("\n=== Начинаем импорт данных ===\n")
        
        # Создаем папку data если её нет
        import os
        if not os.path.exists('data'):
            os.makedirs('data')
            print("Создана папка 'data'")
            print("Поместите файлы Excel в папку 'data'")
            return
        
        # Проверяем структуру файлов перед импортом
        check_excel_file_structure('data/Workshops_import.xlsx')
        
        # Импорт справочников (важен порядок)
        import_material_types(conn, 'data/Material_type_import.xlsx')
        import_product_types(conn, 'data/Product_type_import.xlsx')
        import_workshops(conn, 'data/Workshops_import.xlsx')
        
        # Импорт основной информации
        import_products(conn, 'data/Products_import.xlsx')
        import_product_workshops(conn, 'data/Product_workshops_import.xlsx')
        
        print("\n=== Импорт данных завершен! ===")
        
        # Покажем статистику
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM material_types")
        print(f"Типов материалов: {cur.fetchone()[0]}")
        
        cur.execute("SELECT COUNT(*) FROM product_types")
        print(f"Типов продукции: {cur.fetchone()[0]}")
        
        cur.execute("SELECT COUNT(*) FROM workshops")
        print(f"Цехов: {cur.fetchone()[0]}")
        
        cur.execute("SELECT COUNT(*) FROM products")
        print(f"Продуктов: {cur.fetchone()[0]}")
        
        cur.execute("SELECT COUNT(*) FROM product_workshops")
        print(f"Связей продукция-цех: {cur.fetchone()[0]}")
        
    except FileNotFoundError as e:
        print(f"\n✗ Файл не найден: {e}")
        print("  Убедитесь, что файлы Excel находятся в папке 'data'")
    except Exception as e:
        print(f"\n✗ Ошибка при импорте: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    main()