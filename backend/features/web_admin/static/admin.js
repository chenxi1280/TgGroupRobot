const state = {
  specs: [],
  copyLimit: 40,
  cards: [],
  generatedText: '',
}

const $ = (id) => document.getElementById(id)

const show = (element, visible) => {
  element.classList.toggle('hidden', !visible)
}

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
})[char])

const toast = (message) => {
  const box = $('toast')
  box.textContent = message
  show(box, true)
  window.clearTimeout(box._timer)
  box._timer = window.setTimeout(() => show(box, false), 3200)
}

const api = async (url, options = {}) => {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    let detail = `请求失败：${response.status}`
    try {
      const body = await response.json()
      detail = body.detail || body.message || detail
    } catch {
      // Keep the default detail.
    }
    throw new Error(detail)
  }
  return response.json()
}

const copyText = async (text) => {
  if (!text) throw new Error('复制内容为空')
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall back to textarea copy for local HTTP and mobile webviews.
    }
  }
  const textArea = document.createElement('textarea')
  textArea.value = text
  textArea.setAttribute('readonly', 'true')
  textArea.style.position = 'fixed'
  textArea.style.left = '-9999px'
  textArea.style.top = '0'
  document.body.appendChild(textArea)
  const activeElement = document.activeElement
  textArea.focus()
  textArea.select()
  textArea.setSelectionRange(0, textArea.value.length)
  const ok = document.execCommand('copy')
  document.body.removeChild(textArea)
  if (activeElement instanceof HTMLElement) activeElement.focus()
  if (!ok) throw new Error('浏览器拒绝复制，请手动选择文本复制')
}

const fillSpecSelects = () => {
  const options = state.specs.map((item) => `<option value="${item.days}">${item.label}</option>`).join('')
  $('specSelect').innerHTML = options
  $('filterSpec').innerHTML = `<option value="">全部规格</option>${options}`
  $('copyLimitHint').textContent = `单次复制 ${state.copyLimit} 条`
}

const currentFilters = () => {
  const params = new URLSearchParams()
  if ($('filterSpec').value) params.set('spec_days', $('filterSpec').value)
  if ($('filterStatus').value) params.set('status', $('filterStatus').value)
  if ($('filterKeyword').value.trim()) params.set('keyword', $('filterKeyword').value.trim())
  params.set('limit', '200')
  return params
}

const renderCards = (items) => {
  state.cards = items
  $('selectAllCards').checked = false
  show($('cardsEmpty'), items.length === 0)
  $('cardsBody').innerHTML = items.map((card) => {
    const status = card.used ? '<span class="status-used">已激活</span>' : '<span class="status-free">可用</span>'
    const disabled = card.has_plaintext ? '' : 'disabled'
    return `
      <tr>
        <td><input class="card-check" type="checkbox" value="${escapeHtml(card.id)}" ${disabled}></td>
        <td class="code">${escapeHtml(card.card_code || '历史卡密无明文')}</td>
        <td>${escapeHtml(card.spec_days || '-')}天</td>
        <td>${status}</td>
        <td>${escapeHtml(card.used_by_chat_title || '')}</td>
        <td>${escapeHtml(card.used_by_user_text || '')}</td>
        <td>${escapeHtml(card.owner_text || '')}</td>
        <td>${escapeHtml(formatTime(card.used_at))}</td>
      </tr>
    `
  }).join('')
}

const renderBatches = (items) => {
  $('batchesBody').innerHTML = items.map((batch) => `
    <tr>
      <td class="code">${escapeHtml(batch.batch_no)}</td>
      <td>${escapeHtml(batch.spec_days)}天</td>
      <td>${escapeHtml(batch.quantity)}</td>
      <td>${escapeHtml(batch.used_count)}</td>
      <td>${escapeHtml(batch.copy_count)}</td>
      <td>${escapeHtml(batch.export_count)}</td>
      <td>${escapeHtml(formatTime(batch.created_at))}</td>
    </tr>
  `).join('')
}

const formatTime = (value) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

const loadKeys = async () => {
  const params = currentFilters()
  const cardsResponse = await api(`/admin/api/keys?${params.toString()}`)
  const batchParams = new URLSearchParams()
  if ($('filterSpec').value) batchParams.set('spec_days', $('filterSpec').value)
  if ($('filterKeyword').value.trim()) batchParams.set('keyword', $('filterKeyword').value.trim())
  const batchesResponse = await api(`/admin/api/key-batches?${batchParams.toString()}`)
  renderCards(cardsResponse.data.items)
  renderBatches(batchesResponse.data.items)
}

const selectedCardIds = () =>
  [...document.querySelectorAll('.card-check:checked')]
    .map((input) => Number(input.value))
    .filter(Boolean)

const loadAnnouncement = async () => {
  const response = await api('/admin/api/announcement')
  const data = response.data
  $('announcementEnabled').checked = Boolean(data.enabled)
  $('announcementEntry').value = data.entry_text || ''
  $('announcementUrl').value = data.target_url || ''
  $('announcementMessage').value = data.message_text || ''
}

const showAdminPanel = async (admin) => {
  $('currentAdmin').textContent = admin.display_name || admin.username
  show($('loginPanel'), false)
  show($('adminPanel'), true)
  const specs = await api('/admin/api/key-specs')
  state.specs = specs.data.items || []
  state.copyLimit = specs.data.copy_limit || 40
  fillSpecSelects()
  await Promise.all([loadKeys(), loadAnnouncement()])
}

const boot = async () => {
  try {
    const me = await api('/admin/api/auth/me')
    await showAdminPanel(me.data)
  } catch {
    show($('loginPanel'), true)
    show($('adminPanel'), false)
  }
}

$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    const response = await api('/admin/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        username: $('loginUsername').value.trim(),
        password: $('loginPassword').value,
      }),
    })
    toast('登录成功')
    await showAdminPanel(response.data)
  } catch (error) {
    toast(error.message)
  }
})

$('logoutBtn').addEventListener('click', async () => {
  await api('/admin/api/auth/logout', { method: 'POST', body: '{}' })
  window.location.reload()
})

document.querySelectorAll('.tab').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((item) => item.classList.remove('active'))
    button.classList.add('active')
    show($('tabKeys'), button.dataset.tab === 'keys')
    show($('tabAnnouncement'), button.dataset.tab === 'announcement')
  })
})

$('generateForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    const response = await api('/admin/api/key-batches', {
      method: 'POST',
      body: JSON.stringify({
        spec_days: Number($('specSelect').value),
        quantity: Number($('quantityInput').value),
      }),
    })
    state.generatedText = response.data.copied_text || ''
    $('generatedText').value = state.generatedText
    const total = response.data.batch.quantity
    const copied = response.data.copied_count
    $('generatedHint').textContent = response.data.truncated
      ? `本次 ${total} 条，已准备最近创建的 ${copied} 条`
      : `本次 ${total} 条可直接复制`
    show($('generateResult'), true)
    await loadKeys()
    toast('卡密批次已生成')
  } catch (error) {
    toast(error.message)
  }
})

$('copyGeneratedBtn').addEventListener('click', async () => {
  try {
    await copyText(state.generatedText || $('generatedText').value)
    toast('已复制本次卡密')
  } catch (error) {
    toast(error.message)
  }
})

$('refreshBtn').addEventListener('click', loadKeys)
$('applyFilterBtn').addEventListener('click', loadKeys)

$('selectAllCards').addEventListener('change', (event) => {
  document.querySelectorAll('.card-check:not(:disabled)').forEach((input) => {
    input.checked = event.target.checked
  })
})

const copySelected = async (withMeta) => {
  const ids = selectedCardIds()
  if (!ids.length) {
    toast('请先选择卡密')
    return
  }
  try {
    const response = await api('/admin/api/keys/copy', {
      method: 'POST',
      body: JSON.stringify({ card_ids: ids, with_meta: withMeta }),
    })
    await copyText(response.data.copied_text)
    toast(`已复制 ${response.data.count} 条卡密`)
    await loadKeys()
  } catch (error) {
    toast(error.message)
  }
}

$('copySelectedBtn').addEventListener('click', () => copySelected(false))
$('copySelectedMetaBtn').addEventListener('click', () => copySelected(true))

$('exportBtn').addEventListener('click', () => {
  const params = currentFilters()
  params.delete('limit')
  window.location.href = `/admin/api/keys/export?${params.toString()}`
})

$('announcementForm').addEventListener('submit', async (event) => {
  event.preventDefault()
  try {
    await api('/admin/api/announcement', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: $('announcementEnabled').checked,
        entry_text: $('announcementEntry').value,
        target_url: $('announcementUrl').value,
        message_text: $('announcementMessage').value,
      }),
    })
    toast('公告栏配置已保存')
  } catch (error) {
    toast(error.message)
  }
})

boot()
