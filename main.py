import json
import asyncio
import random
from web3 import AsyncWeb3
from web3.providers.rpc.async_rpc import AsyncHTTPProvider
from eth_account import Account
from eth_account.account import LocalAccount  # для типизации

from config import RPC, use_proxies, gwei_limiter, sleep_between_accounts, async_sync_work, wallets_to_work, \
    NFT_CONTRACT, shuffle_wallet

# Константы путей файлов
PRIVATE_KEYS_FILE = "private_keys.txt"
PROXIES_FILE = "proxies.txt"
ABI_FILE = "ABI.json"

# Загружаем ABI вне функций
with open(ABI_FILE, 'r') as f:
    abi = json.load(f)

# Инициализация AsyncWeb3 с RPC-провайдером из конфига
w3 = AsyncWeb3(AsyncHTTPProvider(RPC))


async def load_proxies():
    proxies = []
    if use_proxies:
        with open(PROXIES_FILE, 'r') as f:
            for line in f:
                proxy = line.strip()
                if proxy:
                    proxies.append(proxy)
    return proxies


def load_private_keys():
    keys = []
    with open(PRIVATE_KEYS_FILE, 'r') as f:
        for line in f:
            key = line.strip()
            if key:
                keys.append(key)
    return keys


async def has_nft(contract, address: str) -> bool:
    try:
        checksum_address = w3.to_checksum_address(address)
        balance = await contract.functions.balanceOf(checksum_address).call()
        return balance > 0
    except Exception as e:
        print(f"[ERROR] Проверка NFT у {address} провалилась: {e}")
        return False


async def mint_nft(contract, account: LocalAccount) -> bool:
    try:
        nonce = await w3.eth.get_transaction_count(account.address)
        gas_price = await w3.eth.gas_price
        gwei_price = gas_price / 1e9

        if gwei_price > gwei_limiter:
            print(f"[INFO] Gwei {gwei_price:.2f} выше лимита {gwei_limiter}, ждем 30 секунд...")
            await asyncio.sleep(30)

        tx = await contract.functions.mint().build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": 200000,
            "gasPrice": gas_price
        })

        signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
        tx_hash = await w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        print(f"[INFO] Mint транзакция отправлена: {tx_hash.hex()} для {account.address}")

        receipt = await w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"[INFO] Транзакция подтверждена в блоке {receipt['blockNumber']}")

        return True

    except Exception as e:
        print(f"[ERROR] Минтинг не удался для {account.address}: {e}")
        return False

async def worker(contract, private_key: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        account = Account.from_key(private_key)
        print(f"[INFO] Обрабатываю кошелек: {account.address}")

        if await has_nft(contract, account.address):
            print(f"[INFO] NFT уже есть у {account.address}, пропускаю.")
            return

        success = await mint_nft(contract, account)

        if success:
            print(f"[INFO] Mint прошел успешно для {account.address}")
        else:
            print(f"[WARN] Mint не выполнен для {account.address}")

        print(f"[INFO] Жду {sleep_between_accounts} секунд перед следующей операцией...")
        await asyncio.sleep(sleep_between_accounts)


async def main():
    contract_address = w3.to_checksum_address(NFT_CONTRACT)
    contract = w3.eth.contract(address=contract_address, abi=abi)

    private_keys = load_private_keys()

    if shuffle_wallet:
        random.shuffle(private_keys)

    semaphore = asyncio.Semaphore(wallets_to_work if async_sync_work else 1)

    tasks = [worker(contract, pk, semaphore) for pk in private_keys]

    if async_sync_work:
        await asyncio.gather(*tasks)
    else:
        for task in tasks:
            await task

if __name__ == '__main__':
    asyncio.run(main())