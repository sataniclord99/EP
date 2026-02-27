import os

class Config:
    SECRET_KEY = 'SWAG'
    DB_HOST = 'localhost'
    DB_PORT = '5432'
    DB_NAME = 'furniture_company'
    DB_USER = 'postgres'
    DB_PASSWORD = '1324'
    
    @staticmethod
    def get_db_url():
        return f"postgresql://{Config.DB_USER}:{Config.DB_PASSWORD}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}"