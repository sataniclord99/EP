"""
Модуль для расчета количества сырья, необходимого для производства продукции.
Соответствует требованиям: метод принимает идентификаторы и параметры,
возвращает целое количество сырья с учетом потерь.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config
import math
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MaterialCalculator:
    """
    Класс для расчета количества сырья для производства продукции.
    """
    
    def __init__(self, db_config=None):
        """
        Инициализация калькулятора с параметрами подключения к БД.
        
        Args:
            db_config: словарь с параметрами подключения к БД
        """
        self.db_config = db_config or {
            'host': Config.DB_HOST,
            'port': Config.DB_PORT,
            'database': Config.DB_NAME,
            'user': Config.DB_USER,
            'password': Config.DB_PASSWORD
        }
    
    def _get_db_connection(self):
        """Установка соединения с базой данных."""
        return psycopg2.connect(
            **self.db_config,
            cursor_factory=RealDictCursor
        )
    
    def _to_float(self, value):
        """Преобразование Decimal в float для вычислений."""
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
    
    def calculate_raw_material(self, product_type_id, material_type_id, 
                               quantity, length, width):
        """
        Расчет количества сырья для производства продукции.
        
        Args:
            product_type_id (int): идентификатор типа продукции
            material_type_id (int): идентификатор типа материала
            quantity (int): количество продукции (целое положительное число)
            length (float): длина изделия (в метрах)
            width (float): ширина изделия (в метрах)
        
        Returns:
            int: необходимое количество сырья в квадратных метрах с учетом потерь
                 или -1 в случае ошибки/некорректных данных
        
        Формула расчета:
            1. Площадь изделия = length * width (в кв. метрах)
            2. Сырье на единицу = площадь * product_coefficient
            3. Общее сырье = сырье_на_единицу * quantity
            4. С учетом потерь = общее_сырье * (1 + loss_percentage)
            5. Результат округляется вверх до целого числа
        """

        try:
            quantity = int(quantity)
            if quantity <= 0:
                logger.error(f"Некорректное количество продукции: {quantity}")
                return -1
            
            length = float(length)
            width = float(width)
            
            if length <= 0 or width <= 0:
                logger.error(f"Размеры должны быть положительными: длина={length}, ширина={width}")
                return -1
            
            if math.isinf(length) or math.isinf(width) or math.isnan(length) or math.isnan(width):
                logger.error(f"Размеры содержат некорректные значения: {length}, {width}")
                return -1
            
        except (ValueError, TypeError) as e:
            logger.error(f"Ошибка преобразования параметров: {e}")
            return -1
        
        conn = None
        cur = None
        
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT coefficient FROM product_types WHERE id = %s
            """, (product_type_id,))
            
            product_type = cur.fetchone()
            if not product_type:
                logger.error(f"Тип продукции с id {product_type_id} не найден")
                return -1
            
            product_coefficient = self._to_float(product_type['coefficient'])
            
            cur.execute("""
                SELECT loss_percentage FROM material_types WHERE id = %s
            """, (material_type_id,))
            
            material_type = cur.fetchone()
            if not material_type:
                logger.error(f"Тип материала с id {material_type_id} не найден")
                return -1
            
            loss_percentage = self._to_float(material_type['loss_percentage'])
            
            area = length * width
            
            material_per_unit = area * product_coefficient
            
            total_material_without_loss = material_per_unit * quantity
            
            total_material_with_loss = total_material_without_loss * (1 + loss_percentage)
            
            result = math.ceil(total_material_with_loss)
            
            logger.info(f"Расчет выполнен успешно: product_type_id={product_type_id}, "
                       f"material_type_id={material_type_id}, quantity={quantity}, "
                       f"длина={length}, ширина={width}, результат={result}")
            
            return result
            
        except psycopg2.Error as e:
            logger.error(f"Ошибка базы данных: {e}")
            return -1
        except Exception as e:
            logger.error(f"Непредвиденная ошибка: {e}")
            return -1
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
    
    def calculate_for_product(self, product_id, quantity, length, width):
        """
        Упрощенный метод расчета для конкретного продукта.
        Автоматически получает типы из информации о продукте.
        
        Args:
            product_id (int): идентификатор продукта
            quantity (int): количество продукции
            length (float): длина изделия (в метрах)
            width (float): ширина изделия (в метрах)
        
        Returns:
            int: необходимое количество сырья или -1 при ошибке
        """
        conn = None
        cur = None
        
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT product_type_id, material_type_id 
                FROM products 
                WHERE id = %s
            """, (product_id,))
            
            product = cur.fetchone()
            if not product:
                logger.error(f"Продукт с id {product_id} не найден")
                return -1
            
            return self.calculate_raw_material(
                product['product_type_id'],
                product['material_type_id'],
                quantity,
                length,
                width
            )
            
        except Exception as e:
            logger.error(f"Ошибка при расчете для продукта {product_id}: {e}")
            return -1
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()


def test_calculator():
    """Функция для тестирования калькулятора."""
    calculator = MaterialCalculator()
    
    test_cases = [
        (1, 1, 10, 2.5, 1.8, None),
        (1, 1, -5, 2.5, 1.8, -1),
        (999, 1, 10, 2.5, 1.8, -1),
        (1, 999, 10, 2.5, 1.8, -1),
        (1, 1, 10, -1.5, 1.8, -1),
        (1, 1, 10, 2.5, 0, -1),
    ]
    
    print("=" * 70)
    print("ТЕСТИРОВАНИЕ КАЛЬКУЛЯТОРА СЫРЬЯ")
    print("=" * 70)
    
    for i, (pt_id, mt_id, qty, length, width, expected) in enumerate(test_cases, 1):
        result = calculator.calculate_raw_material(pt_id, mt_id, qty, length, width)
        
        status = "✓" if (expected is None and result > 0) or result == expected else "✗"
        print(f"\nТест {i}: {status}")
        print(f"  Входные данные: product_type_id={pt_id}, material_type_id={mt_id}, "
              f"quantity={qty}, длина={length}м, ширина={width}м")
        print(f"  Результат: {result}")
        
        if result > 0:
            print(f"  ✅ Расчет успешен, необходимо сырья: {result} кв.м")
        elif result == -1:
            print(f"  ❌ Ошибка (возвращено -1)")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_calculator()