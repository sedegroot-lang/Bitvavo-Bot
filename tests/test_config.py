import json


import sys
sys.path.append('..')
from modules.config import load_config, save_config, CONFIG_PATH
import os

def test_config_load():
    config = load_config()
    # SMA_SHORT is consumed via cfg.get('SMA_SHORT', default) and not persisted
    # in the base config. MAX_OPEN_TRADES IS persisted and required.
    assert 'MAX_OPEN_TRADES' in config
    assert isinstance(config, dict) and len(config) > 10
    print('Config test geslaagd!')

def test_config_reload():
    config = load_config()
    config['TEST_PARAM'] = 123
    save_config(config)
    config2 = load_config()
    assert config2['TEST_PARAM'] == 123
    print('Config reload test geslaagd!')
    # Cleanup
    del config2['TEST_PARAM']
    save_config(config2)

def test_config_file_missing():
    backup = CONFIG_PATH + '.bak'
    os.rename(CONFIG_PATH, backup)
    try:
        try:
            load_config()
        except Exception:
            print('Config missing test geslaagd!')
    finally:
        os.rename(backup, CONFIG_PATH)

if __name__ == '__main__':
    test_config_load()
    test_config_reload()
    test_config_file_missing()

if __name__ == '__main__':
    test_config_load()
