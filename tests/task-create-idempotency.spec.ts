import { test, expect } from '@playwright/test'
import { API_KEY_HEADER, deleteTestTask } from './helpers'

test.describe('Task creation idempotency', () => {
  const created = new Set<number>()
  test.afterEach(async ({ request }) => {
    for (const id of created) await deleteTestTask(request, id).catch(() => {})
    created.clear()
  })

  test('identical retries return the original task, including simultaneous requests', async ({ request }) => {
    const data = { title: `retry-task-${Date.now()}`, assigned_to: 'clearpage-validator',
      idempotency_key: `clearpage:test-${Date.now()}:validation`, metadata: { simulation_only: true } }
    const responses = await Promise.all(Array.from({ length: 5 }, () => request.post('/api/tasks', {
      headers: API_KEY_HEADER, data,
    })))
    const payloads = await Promise.all(responses.map(response => response.json()))
    expect(responses.map(response => response.status()).sort()).toEqual([200, 200, 200, 200, 201])
    const ids = payloads.map(payload => payload.task.id)
    ids.forEach(id => created.add(id))
    expect(new Set(ids).size).toBe(1)
    expect(payloads.filter(payload => payload.idempotent_replay)).toHaveLength(4)

    const conflict = await request.post('/api/tasks', { headers: API_KEY_HEADER,
      data: { ...data, title: data.title + ' changed' } })
    expect(conflict.status()).toBe(409)
  })

  test('different idempotency keys create distinct tasks', async ({ request }) => {
    const title = `separate-task-${Date.now()}`
    const first = await request.post('/api/tasks', { headers: API_KEY_HEADER,
      data: { title, idempotency_key: `clearpage:separate-a-${Date.now()}` } })
    const second = await request.post('/api/tasks', { headers: API_KEY_HEADER,
      data: { title, idempotency_key: `clearpage:separate-b-${Date.now()}` } })
    expect(first.status()).toBe(201)
    expect(second.status()).toBe(201)
    const firstId = (await first.json()).task.id
    const secondId = (await second.json()).task.id
    created.add(firstId)
    created.add(secondId)
    expect(firstId).not.toBe(secondId)
  })
})
