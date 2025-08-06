import os
from datetime import datetime

def main():
    # Путь к репозиторию
    base_dir = r'D:\01\mygithub\MitilVPN'
    
    print("=" * 50)
    print("🚀 Отправка файлов на GitHub")
    print("=" * 50)
    
    # Переходим в директорию репозитория
    try:
        os.chdir(base_dir)
        print(f"📂 Перешли в директорию: {base_dir}")
    except Exception as e:
        print(f"❌ Ошибка: не удается перейти в директорию {base_dir}")
        print(f"   {str(e)}")
        return

    # Показываем текущий статус
    print("\n📊 Текущий статус Git:")
    os.system('git status')
    
    print("\n" + "-" * 30)
    
    # Добавляем ВСЕ измененные файлы
    print("➕ Добавляем все файлы...")
    add_result = os.system('git add .')
    
    if add_result == 0:
        print("✅ Файлы добавлены успешно")
        
        # Создаем коммит с временной меткой
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_message = f"Update files - {timestamp}"
        
        print(f"💬 Создаем коммит: {commit_message}")
        commit_result = os.system(f'git commit -m "{commit_message}"')
        
        if commit_result == 0:
            print("✅ Коммит создан успешно")
            
            print("⬆️ Отправляем на GitHub...")
            push_result = os.system('git push')
            
            if push_result == 0:
                print("🎉 Файлы успешно отправлены на GitHub!")
            else:
                print("❌ Ошибка при отправке на GitHub")
                print("   Возможные причины:")
                print("   - Проблемы с интернетом")
                print("   - Нужна авторизация")
                print("   - Проблемы с репозиторием")
        else:
            print("ℹ️ Нет изменений для коммита")
    else:
        print("❌ Ошибка при добавлении файлов")

    print("\n" + "=" * 50)
    print("✅ Скрипт завершен!")
    print("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Операция прервана пользователем")
    except Exception as e:
        print(f"\n❌ Произошла ошибка: {str(e)}")
        input("Нажмите Enter для выхода...")