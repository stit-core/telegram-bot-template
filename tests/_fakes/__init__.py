"""Фейки для тестов: фейковый бэкенд (JsonApi) и Delivery — мокаем порт/границу, не транспорт.

Кэш и Redis подменяются фейками самой lib'ы: `cachekit.MemoryCache` и
`testkit.bottest.MemoryRedis` (та же семантика TTL/NX/Lua-скриптов, что у прода).
"""
