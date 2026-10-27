#!/usr/bin/env python
import os
import sys

def main():
    # Apuntamos a la configuración principal de nuestro proyecto FlySwap
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'flyswap.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
