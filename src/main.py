import sys
from pathlib import Path
import argparse

sys.path.append(str(Path(__file__).parent.parent))

from utils.face_recognition_system import initialize_face_recognition_system


def main():
    parser = argparse.ArgumentParser(description='Система распознавания лиц с управлением замком')
    parser.add_argument('--mode', choices=['test', 'infinity'], default='test', help='Режим работы: test (тестовый) или infinity (непрерывный мониторинг)')
    
    args = parser.parse_args()
    
    face_system = initialize_face_recognition_system()
    
    try:
        if args.mode == 'test':
            print("Запуск тестового режима системы распознавания лиц.")
            face_system.test_mode()

        elif args.mode == 'infinity':
            print("Запуск непрерывного режима мониторинга.")
            face_system.start_infinity_monitoring()
        
    except KeyboardInterrupt:
        print("\nПрограмма остановлена")
    except Exception as e:
        print(f"Произошла ошибка: {e}")
    finally:
        face_system.stop()


if __name__ == '__main__':
    main()
