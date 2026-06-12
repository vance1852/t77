import pymysql

# 使用纯 Python 的 PyMySQL 作为 MySQLdb 的替代，避免原生编译依赖
pymysql.install_as_MySQLdb()
