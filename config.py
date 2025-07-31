# Soft settings
async_sync_work = 0  # 0 - синхронная работа, 1 - асинхронная
wallets_to_work = 10  # используется если async_sync_work = 1
use_proxies = True  # использовать прокси True/False
sleep_between_accounts = 10  # таймаут между аккаунтами в секундах
gwei_limiter = 1  # если gwei текущий выше этого значения, ждем
shuffle_wallet = True # Брать рандомные кошельки, для рандомизации

# Soft data
NFT_CONTRACT = '0x26d85a13212433fe6a8381969c2b0db390a0b0ae'
RPC = 'https://eth-pokt.nodies.app'