import json
import asyncio
import random
from web3 import AsyncWeb3
from web3.providers.rpc.async_rpc import AsyncHTTPProvider
from eth_account import Account
from eth_account.account import LocalAccount  # для типизации

from config import (
    RPC,
    use_proxies,
    gwei_limiter,
    sleep_between_accounts,
    async_sync_work,
    wallets_to_work,
    NFT_CONTRACT,
    shuffle_wallet
)

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


async def prepare_gas_params(contract, account: LocalAccount):
    """
    Получаем динамические параметры газа для EIP-1559 транзакции:
    baseFeePerGas, maxPriorityFeePerGas, maxFeePerGas и gas limit с запасом.
    """

    latest_block = await w3.eth.get_block('pending')
    base_fee = latest_block.get('baseFeePerGas')
    if base_fee is None:
        # fallback для сетей без поддержки EIP-1559
        gas_price = await w3.eth.gas_price
        gas_limit = await contract.functions.mint().estimate_gas({'from': account.address})
        return gas_price, None, gas_limit

    # Берём рекомендованный max priority fee (чаёк)
    max_priority_fee_per_gas = await w3.eth.max_priority_fee

    # Формула maxFeePerGas = baseFee * 2 + maxPriorityFeePerGas — как в MetaMask
    max_fee_per_gas = base_fee * 2 + max_priority_fee_per_gas

    # Параметры для оценки gasLimit
    tx_params = {
        'from': account.address,
        'maxPriorityFeePerGas': max_priority_fee_per_gas,
        'maxFeePerGas': max_fee_per_gas,
        'type': 2
    }
    gas_limit = await contract.functions.mint().estimate_gas(tx_params)

    # Добавляем запас 50%, как делают кошельки
    gas_limit = int(gas_limit * 1.5)

    return max_fee_per_gas, max_priority_fee_per_gas, gas_limit


async def mint_nft(contract, account: LocalAccount) -> bool:
    try:
        nonce = await w3.eth.get_transaction_count(account.address)

        max_fee_per_gas, max_priority_fee_per_gas, gas_limit = await prepare_gas_params(contract, account)

        # Если лимит газа не оценился — ставим запасной default
        gas_limit = gas_limit or 200000

        # Проверяем лимит max_fee_per_gas, чтобы не отправлять слишком дорогие транзакции
        gwei_limiter_wei = int(gwei_limiter * 1e9)
        if max_fee_per_gas > gwei_limiter_wei:
            print(f"[INFO] Max fee per gas ({max_fee_per_gas / 1e9:.2f} gwei) выше лимита {gwei_limiter}, ждем 30 секунд...")
            await asyncio.sleep(30)

        tx = await contract.functions.mint().build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": gas_limit,
            "maxPriorityFeePerGas": max_priority_fee_per_gas,
            "maxFeePerGas": max_fee_per_gas,
            "type": 2
        })

        signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
        tx_hash = await w3.eth.send_raw_transaction(signed_tx.rawTransaction)

        print(f"[INFO] Mint транзакция отправлена: {tx_hash.hex()} для {account.address}")

        receipt = await w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"[INFO] Транзакция подтверждена в блоке {receipt['blockNumber']}")

        return True

    except Exception as e:
        print(f"[ERROR] Минтинг не удался для {account.address}: {e}")
        return False


async def worker(contract, private_key: str):
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


async def main():
    contract_address = w3.to_checksum_address(NFT_CONTRACT)
    contract = w3.eth.contract(address=contract_address, abi=abi)

    private_keys = load_private_keys()
    if shuffle_wallet:
        random.shuffle(private_keys)

    max_parallel = wallets_to_work if async_sync_work else 1
    semaphore = asyncio.Semaphore(max_parallel)

    tasks = []

    loop_time = asyncio.get_event_loop().time()  # Время старта

    for i, pk in enumerate(private_keys):
        scheduled_start = loop_time + i * sleep_between_accounts

        now = asyncio.get_event_loop().time()
        wait_for_start = scheduled_start - now
        if wait_for_start > 0:
            print(f"[INFO] Ждем {wait_for_start:.2f} секунд до запуска аккаунта {i+1}")
            await asyncio.sleep(wait_for_start)

        await semaphore.acquire()

        async def task_wrapper(pk_inner):
            try:
                await worker(contract, pk_inner)
            finally:
                semaphore.release()

        task = asyncio.create_task(task_wrapper(pk))
        tasks.append(task)

    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
