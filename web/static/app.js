// DingTalk Exporter - Frontend Application

const API_BASE = '';

const state = {
    conversations: [],
    currentCid: null,
    currentOffset: 0,
    currentLimit: 50,
    totalMessages: 0,
    convOffset: 0,
    convLimit: 50,
    myUid: '',
};

// --- API helpers ---

async function _apiError(resp) {
    let msg = `API error: ${resp.status}`;
    try {
        const data = await resp.json();
        if (data && data.detail) {
            msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
        }
    } catch (e) { /* not JSON */ }
    return new Error(msg);
}

async function apiGet(path) {
    const resp = await fetch(API_BASE + path);
    if (!resp.ok) throw await _apiError(resp);
    return resp.json();
}

async function apiPost(path, body) {
    const opts = { method: 'POST' };
    if (body !== undefined) {
        opts.headers = { 'Content-Type': 'application/json' };
        opts.body = JSON.stringify(body);
    }
    const resp = await fetch(API_BASE + path, opts);
    if (!resp.ok) throw await _apiError(resp);
    return resp.json();
}

// --- Format helpers ---

function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatRelativeTime(ts) {
    if (!ts) return '';
    const now = Date.now();
    const diff = now - ts;
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff/60000)}分钟前`;
    if (diff < 86400000) return `${Math.floor(diff/3600000)}小时前`;
    if (diff < 604800000) return `${Math.floor(diff/86400000)}天前`;
    return formatTime(ts);
}

function formatSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return `${bytes.toFixed(1)} ${units[i]}`;
}

function renderInlineImages(html) {
    // No longer used — kept for compatibility
    return html;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    // Bold: **text** or #### heading
    html = html.replace(/^#{1,4}\s+(.+)$/gm, '<strong>$1</strong>');
    // Links: [[text]](url)
    html = html.replace(/\[\[([^\]]*)\]\]\(([^)]*)\)/g, '<span style="color:#3498db">[$1]</span>');
    // @mentions
    html = html.replace(/@(\S+?\(\S+?\))/g, '<span style="color:#3498db">@$1</span>');
    // Newlines to <br>
    html = html.replace(/\n/g, '<br>');
    return html;
}

// --- Conversations ---
let _convTotal = 0;       // total from API
let _convLoading = false; // prevent duplicate loads
let _convFilter = 'all';  // all | group | single
let _convSearch = '';     // search keyword

async function loadConversations(reset = false) {
    if (reset) {
        state.convOffset = 0;
        state.conversations = [];
        _convTotal = 0;
    }

    // All loaded
    if (_convTotal > 0 && state.conversations.length >= _convTotal) return;
    if (_convLoading) return;
    _convLoading = true;

    const params = new URLSearchParams({
        limit: state.convLimit,
        offset: state.convOffset,
    });

    try {
        const data = await apiGet(`/api/conversations?${params}`);
        _convTotal = data.total;
        state.conversations = reset ? data.conversations : [...state.conversations, ...data.conversations];
        state.convOffset += data.conversations.length;
        renderConversations(_convTotal);
    } finally {
        _convLoading = false;
    }
}

// Infinite scroll for conversation list
function _onConvListScroll() {
    const el = document.getElementById('convList');
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
    if (atBottom && !_convLoading && state.conversations.length < _convTotal) {
        loadConversations(false);
    }
}

function _getFilteredConversations() {
    let list = state.conversations;
    // Filter by type
    if (_convFilter === 'group') {
        list = list.filter(c => c.type === 'group');
    } else if (_convFilter === 'single') {
        list = list.filter(c => c.type === 'single');
    }
    // Filter by search
    if (_convSearch) {
        const kw = _convSearch.toLowerCase();
        list = list.filter(c => (c.title || '').toLowerCase().includes(kw));
    }
    return list;
}

function renderConversations(total) {
    const list = document.getElementById('convList');
    const count = document.getElementById('convCount');

    const filtered = _getFilteredConversations();
    count.textContent = `${filtered.length}/${total}`;

    if (filtered.length === 0 && state.conversations.length > 0) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#999">无匹配会话</div>';
        return;
    }

    list.innerHTML = filtered.map(conv => {
        const unread = conv.unread_count > 0 ? `<span class="unread-badge">${conv.unread_count > 99 ? '99+' : conv.unread_count}</span>` : '';
        return `
        <div class="conv-item ${conv.cid === state.currentCid ? 'active' : ''}" data-cid="${conv.cid}">
            <div class="conv-title">
                <span class="conv-type-badge ${conv.type}">${conv.type === 'group' ? '群' : '单聊'}</span>
                ${escapeHtml(conv.title || conv.cid)}
                ${unread}
            </div>
            <div class="conv-subtitle">
                <span>${conv.member_count ? conv.member_count + '人' : ''}</span>
                <span>${formatRelativeTime(conv.last_modify)}</span>
            </div>
        </div>
    `}).join('');

    // Re-bind scroll
    list.removeEventListener('scroll', _onConvListScroll);
    list.addEventListener('scroll', _onConvListScroll);

    // Bind clicks
    list.querySelectorAll('.conv-item').forEach(el => {
        el.addEventListener('click', () => {
            const cid = el.dataset.cid;
            selectConversation(cid);
        });
    });
}

async function selectConversation(cid) {
    state.currentCid = cid;
    state.currentOffset = 0;

    // Update sidebar active state
    document.querySelectorAll('.conv-item').forEach(el => {
        el.classList.toggle('active', el.dataset.cid === cid);
    });

    // Show message view
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('searchView').style.display = 'none';
    document.getElementById('messageView').style.display = 'flex';

    const conv = state.conversations.find(c => c.cid === cid);
    document.getElementById('convTitle').textContent = conv ? conv.title : cid;
    document.getElementById('convMeta').textContent = conv ?
        `${conv.type === 'group' ? '群聊' : '单聊'} · ${conv.member_count || ''}人` : '';

    await loadMessages();
}

// --- Messages ---

async function loadMessages() {
    if (!state.currentCid) return;

    const params = new URLSearchParams({
        limit: state.currentLimit,
        offset: state.currentOffset,
    });

    const data = await apiGet(`/api/conversations/${state.currentCid}/messages?${params}`);
    state.totalMessages = data.total;

    renderMessages(data.messages);
    renderPagination();
}

function renderMessages(messages) {
    const list = document.getElementById('messageList');
    const myUid = state.myUid;

    // Build HTML with date separators
    let html = '';
    let lastDateStr = '';

    messages.forEach(msg => {
        // Date separator
        const msgDate = msg.created_at_str ? msg.created_at_str.split(' ')[0] : '';
        if (msgDate && msgDate !== lastDateStr) {
            lastDateStr = msgDate;
            const weekday = _getWeekday(msg.created_at);
            html += `<div class="msg-date-sep"><span>${escapeHtml(msgDate)} ${weekday}</span></div>`;
        }

        const isSelf = String(msg.sender_id) === myUid;
        let contentHtml = '';

        // Render based on content type
        switch (msg.content_type) {
            case 1: // Text
                contentHtml = escapeHtml(msg.text);
                // Highlight @mentions
                if (msg.at_ids && Object.keys(msg.at_ids).length > 0) {
                    for (const [uid, name] of Object.entries(msg.at_ids)) {
                        contentHtml = contentHtml.replace(
                            new RegExp(`@${uid}`, 'g'),
                            `<span style="color:#3498db">@${escapeHtml(name)}</span>`
                        );
                    }
                }
                break;
            case 2: // Image
                const imgInfo = msg.image_info || {};
                const imgSrc = imgInfo.src;
                if (imgSrc) {
                    contentHtml = '<a href="' + imgSrc + '" target="_blank"><img class="msg-image" src="' + imgSrc + '" alt="图片" style="max-width:100%;cursor:pointer"></a>';
                } else {
                    contentHtml = '<div class="msg-image-placeholder">[图片未缓存到本地]</div>';
                }
                break;
            case 300: // Voice
                contentHtml = '[语音消息]';
                break;
            case 501: // File
                const fileAtt = (msg.attachments || []).find(a => a.filename);
                if (fileAtt) {
                    const fname = escapeHtml(fileAtt.filename);
                    const fsize = formatSize(fileAtt.file_size);
                    if (fileAtt.local_available) {
                        const dlUrl = '/api/local-file?path=' + encodeURIComponent(fileAtt.local_path);
                        contentHtml = '<div class="msg-file"><span class="msg-file-icon">\uD83D\uDCCE</span><div class="msg-file-info"><a class="msg-file-name msg-file-link" href="' + dlUrl + '" target="_blank">' + fname + '</a><div class="msg-file-size">' + fsize + ' · 可打开</div></div></div>';
                    } else {
                        contentHtml = '<div class="msg-file"><span class="msg-file-icon">\uD83D\uDCCE</span><div class="msg-file-info"><div class="msg-file-name">' + fname + '</div><div class="msg-file-size">' + fsize + '</div></div></div>';
                    }
                } else {
                    contentHtml = '[文件]';
                }
                break;
            case 1101: // Call
                contentHtml = '[通话记录]';
                break;
            case 1400: // Approval
                contentHtml = msg.text ?
                    `<div class="msg-rich-text">${formatMarkdown(msg.text)}</div>` :
                    '[审批消息]';
                break;
            case 2900:
            case 2950: // Interactive cards
                contentHtml = msg.text ?
                    `<div class="msg-card">${escapeHtml(msg.text).substring(0, 500)}</div>` :
                    '[互动卡片]';
                break;
            case 3100: // Quote
            case 1200: // Rich text
            case 1201:
            case 1202:
                let quoteText = msg.text ? escapeHtml(msg.text).substring(0, 500) : '';
                // Replace [图片] with actual images from image_info
                const quoteImgInfo = msg.image_info || {};
                const quoteImgs = quoteImgInfo.images || [];
                if (quoteImgs.length > 0) {
                    let imgIdx = 0;
                    quoteText = quoteText.replace(/\[图片\]/g, () => {
                        if (imgIdx < quoteImgs.length && quoteImgs[imgIdx].src) {
                            const src = quoteImgs[imgIdx].src;
                            imgIdx++;
                            return `<img class="msg-image" src="${src}" alt="图片" style="max-width:100%;cursor:pointer">`;
                        }
                        imgIdx++;
                        return '<span style="display:inline-block;padding:2px 8px;background:#f0f0f0;border-radius:3px;color:#999;font-size:12px;border:1px solid #ddd">图片(未缓存)</span>';
                    });
                } else {
                    // No image_info - show placeholders
                    quoteText = quoteText.replace(/\[图片\]/g, '<span style="display:inline-block;padding:2px 8px;background:#f0f0f0;border-radius:3px;color:#999;font-size:12px;border:1px solid #ddd">图片(原消息中)</span>');
                }
                if (msg.content_type === 3100) {
                    contentHtml = quoteText ? `<div class="msg-quote">${quoteText}</div>` : '[引用消息]';
                } else {
                    contentHtml = quoteText ? `<div class="msg-rich-text">${quoteText}</div>` : '[富文本消息]';
                }
                break;
            default:
                contentHtml = msg.text ? escapeHtml(msg.text) : `[${msg.content_type_name || '消息'}]`;
        }

        html += `
            <div class="msg-item ${isSelf ? 'self' : ''}">
                <div class="msg-sender">${escapeHtml(msg.sender_name)}</div>
                <div class="msg-bubble">${contentHtml}</div>
                <div class="msg-time">${msg.created_at_str || formatTime(msg.created_at)}</div>
            </div>
        `;
    });

    // Replace inline image markers with actual <img> tags
    html = renderInlineImages(html);

    list.innerHTML = html;

    // Bind image events via delegation
    list.querySelectorAll('.msg-image').forEach(img => {
        img.addEventListener('click', function() {
            openLightbox(this.src);
        });
        img.addEventListener('error', function() {
            this.outerHTML = '<div class="msg-image-placeholder">[图片加载失败]</div>';
        });
    });

    // Scroll to bottom
    list.scrollTop = list.scrollHeight;
}

function _getWeekday(ts) {
    if (!ts) return '';
    const days = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
    try {
        const d = new Date(ts);
        return days[d.getDay()];
    } catch { return ''; }
}

function renderPagination() {
    const container = document.getElementById('messagePagination');
    const totalPages = Math.ceil(state.totalMessages / state.currentLimit);
    // Page 1 = most recent messages, page totalPages = oldest
    const currentPage = Math.floor(state.currentOffset / state.currentLimit) + 1;

    if (totalPages <= 1) {
        container.innerHTML = `<span>共 ${state.totalMessages} 条消息</span>`;
        return;
    }

    let html = '';

    // "更早" = go to next page (older messages)
    if (currentPage < totalPages) {
        html += `<button onclick="goToPage(${currentPage + 1})">更早的消息</button>`;
    }

    // Page numbers
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    html += ` `;
    for (let p = startPage; p <= endPage; p++) {
        html += `<button class="${p === currentPage ? 'active' : ''}" onclick="goToPage(${p})">${p}</button>`;
    }

    // "最新" = go to previous page (newer messages)
    if (currentPage > 1) {
        html += `<button onclick="goToPage(${currentPage - 1})">最新消息</button>`;
    }

    html += ` <span>第${currentPage}/${totalPages}页 共${state.totalMessages}条</span>`;
    container.innerHTML = html;
}

function goToPage(page) {
    state.currentOffset = (page - 1) * state.currentLimit;
    loadMessages();
}

// --- Search ---

async function doSearch() {
    const query = document.getElementById('searchInput').value.trim();
    if (!query) return;

    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('messageView').style.display = 'none';
    document.getElementById('searchView').style.display = 'flex';
    document.getElementById('searchTitle').textContent = `搜索: "${query}"`;

    const data = await apiGet(`/api/search?q=${encodeURIComponent(query)}`);
    const results = document.getElementById('searchResults');

    if (data.messages.length === 0) {
        results.innerHTML = '<div class="loading">没有找到匹配的消息</div>';
        return;
    }

    results.innerHTML = data.messages.map(msg => `
        <div class="msg-item" style="max-width:100%">
            <div class="msg-sender">
                ${escapeHtml(msg.sender_name)}
                <span style="margin-left:8px;font-size:11px;color:#999">${msg.created_at_str}</span>
            </div>
            <div class="msg-bubble">${highlightSearch(escapeHtml(msg.text), query)}</div>
        </div>
    `).join('');
}

function highlightSearch(text, query) {
    if (!text || !query) return text;
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

// --- Sync ---

async function loadSyncStatus() {
    try {
        const state = await apiGet('/api/sync/status');
        const el = document.getElementById('syncStatus');
        if (state.is_syncing) {
            el.textContent = '同步中...';
        } else if (state.last_sync_time_str) {
            el.textContent = `上次同步: ${state.last_sync_time_str}`;
        } else {
            el.textContent = '尚未同步';
        }
    } catch (e) {
        document.getElementById('syncStatus').textContent = '状态未知';
    }
}

async function triggerSync() {
    const btn = document.getElementById('syncBtn');
    btn.disabled = true;
    btn.textContent = '同步中...';

    try {
        await apiPost('/api/sync/trigger');
        document.getElementById('syncStatus').textContent = '同步已触发...';

        // Poll for completion
        const poll = setInterval(async () => {
            try {
                const s = await apiGet('/api/sync/status');
                if (!s.is_syncing) {
                    clearInterval(poll);
                    btn.disabled = false;
                    btn.textContent = '手动同步';
                    loadSyncStatus();
                    // Reload conversations if we have one selected
                    if (state.currentCid) {
                        loadMessages();
                    }
                }
            } catch (e) {}
        }, 3000);
    } catch (e) {
        btn.disabled = false;
        btn.textContent = '手动同步';
        alert('同步失败: ' + e.message);
    }
}

// --- Exports ---

let _exportAllConvs = [];   // all conversations for the export modal
let _exportSelected = {};   // cid -> true/false
let _exportFilter = 'all';  // all | group | single — type filter in export modal

async function loadExports() {
    const data = await apiGet('/api/exports');
    const list = document.getElementById('exportList');

    if (data.exports.length === 0) {
        list.innerHTML = '<div style="color:#888;padding:20px 0">暂无导出文件</div>';
        return;
    }

    list.innerHTML = data.exports.map(exp => {
        const isDir = exp.type === 'directory';
        const badge = isDir ? '<span style="font-size:11px;padding:1px 5px;border-radius:3px;background:#e1f0ff;color:#2196f3;margin-right:6px">含附件</span>' : '';
        const dlUrl = exp.download_url || `/api/exports/${encodeURIComponent(exp.filename)}`;
        return `
        <div class="export-item">
            <div>
                <div class="export-name">${badge}${escapeHtml(exp.filename)}</div>
                <div class="export-time">${formatTime(exp.modified * 1000)}</div>
            </div>
            <div>
                <span class="export-size">${isDir ? '目录' : formatSize(exp.size)}</span>
                <a class="export-download" href="${dlUrl}" download>下载${isDir ? ' ZIP' : ''}</a>
            </div>
        </div>
    `;
    }).join('');
}

async function loadExportConvList(keyword) {
    const el = document.getElementById('exportConvList');
    el.innerHTML = '<div class="loading">加载会话列表...</div>';

    // Fetch all conversations (paginated)
    let all = [];
    let offset = 0;
    const limit = 200;
    while (true) {
        let url = `/api/conversations?limit=${limit}&offset=${offset}`;
        const data = await apiGet(url);
        all = all.concat(data.conversations);
        if (all.length >= data.total) break;
        offset += limit;
    }

    _exportAllConvs = all;

    // Restore previous selections
    renderExportConvList(keyword || '');
}

function renderExportConvList(keyword) {
    const el = document.getElementById('exportConvList');
    let filtered = _exportAllConvs;
    // Filter by type
    if (_exportFilter === 'group') {
        filtered = filtered.filter(c => c.type === 'group');
    } else if (_exportFilter === 'single') {
        filtered = filtered.filter(c => c.type === 'single');
    }
    // Filter by search keyword
    if (keyword) {
        const kw = keyword.toLowerCase();
        filtered = filtered.filter(c => (c.title || '').toLowerCase().includes(kw));
    }

    const selectedNum = Object.values(_exportSelected).filter(Boolean).length;
    document.getElementById('selectedCount').textContent = `已选 ${selectedNum} 个`;
    document.getElementById('exportSelectedBtn').disabled = selectedNum === 0;

    // Update select-all checkbox state
    const allCb = document.getElementById('selectAllCbs');
    const allChecked = filtered.length > 0 && filtered.every(c => _exportSelected[c.cid]);
    allCb.checked = allChecked;

    if (filtered.length === 0) {
        el.innerHTML = '<div style="padding:20px;color:#888">无匹配会话</div>';
        return;
    }

    el.innerHTML = filtered.map(c => `
        <div class="export-conv-row" data-cid="${c.cid}">
            <input type="checkbox" class="ecr-cb" data-cid="${c.cid}" ${_exportSelected[c.cid] ? 'checked' : ''}>
            <span class="ecr-badge ${c.type}">${c.type === 'group' ? '群' : '单'}</span>
            <span class="ecr-title">${escapeHtml(c.title || c.cid)}</span>
        </div>
    `).join('');

    // Bind checkbox clicks
    el.querySelectorAll('.ecr-cb').forEach(cb => {
        cb.addEventListener('change', e => {
            e.stopPropagation();
            _exportSelected[cb.dataset.cid] = cb.checked;
            const n = Object.values(_exportSelected).filter(Boolean).length;
            document.getElementById('selectedCount').textContent = `已选 ${n} 个`;
            document.getElementById('exportSelectedBtn').disabled = n === 0;
        });
    });

    // Bind row clicks (toggle checkbox)
    el.querySelectorAll('.export-conv-row').forEach(row => {
        row.addEventListener('click', e => {
            if (e.target.tagName === 'INPUT') return; // checkbox handles itself
            const cb = row.querySelector('.ecr-cb');
            cb.checked = !cb.checked;
            cb.dispatchEvent(new Event('change'));
        });
    });
}

// --- AI analysis ---

let _aiConfigured = false;
let _aiConfig = null;

function _aiSetStatus(id, text, isError) {
    const el = document.getElementById(id);
    el.textContent = text || '';
    el.classList.toggle('error', !!isError);
}

function _inlineMarkdown(text) {
    // Protect inline code so bold/link rules do not touch it
    const codes = [];
    let html = text.replace(/`([^`]+)`/g, (m, code) => {
        codes.push(code);
        return `\u0000${codes.length - 1}\u0000`;
    });

    html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
        if (!/^(https?:\/\/|mailto:|\/|#)/i.test(url) || /["'<>]/.test(url)) {
            return label;
        }
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    });
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    html = html.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    html = html.replace(/\u0000(\d+)\u0000/g, (m, i) => `<code>${codes[i]}</code>`);
    return html;
}

function _splitTableRow(row) {
    return row.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
        .split('|').map(cell => cell.trim());
}

function renderAiMarkdown(text) {
    // Escape first: model output is untrusted
    const lines = escapeHtml(text || '').split('\n');
    let html = '';
    let listType = null;
    let listItems = [];
    let para = [];
    let i = 0;

    const flushList = () => {
        if (listItems.length) {
            html += `<${listType}>${listItems.join('')}</${listType}>`;
            listItems = [];
            listType = null;
        }
    };
    const flushPara = () => {
        if (para.length) {
            html += `<p>${para.join('<br>')}</p>`;
            para = [];
        }
    };
    const flushAll = () => { flushPara(); flushList(); };

    while (i < lines.length) {
        const line = lines[i];
        const trimmed = line.trim();

        // Fenced code block
        if (trimmed.startsWith('```')) {
            flushAll();
            const code = [];
            i++;
            while (i < lines.length && !lines[i].trim().startsWith('```')) {
                code.push(lines[i]);
                i++;
            }
            i++; // closing fence
            html += `<pre><code>${code.join('\n')}</code></pre>`;
            continue;
        }

        if (!trimmed) {
            flushAll();
            i++;
            continue;
        }

        // Horizontal rule
        if (/^([-*_])\1{2,}$/.test(trimmed)) {
            flushAll();
            html += '<hr>';
            i++;
            continue;
        }

        // Table: header line followed by a separator line
        if (trimmed.includes('|') && i + 1 < lines.length &&
            /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(lines[i + 1])) {
            flushAll();
            const headers = _splitTableRow(trimmed);
            i += 2;
            const rows = [];
            while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
                rows.push(_splitTableRow(lines[i].trim()));
                i++;
            }
            html += '<table class="ai-md-table"><thead><tr>' +
                headers.map(h => `<th>${_inlineMarkdown(h)}</th>`).join('') +
                '</tr></thead><tbody>';
            rows.forEach(row => {
                html += '<tr>' + headers.map((_, idx) =>
                    `<td>${_inlineMarkdown(row[idx] || '')}</td>`).join('') + '</tr>';
            });
            html += '</tbody></table>';
            continue;
        }

        // Headings
        const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
            flushAll();
            const level = Math.min(heading[1].length + 2, 6);
            html += `<h${level}>${_inlineMarkdown(heading[2])}</h${level}>`;
            i++;
            continue;
        }

        // Blockquote (">" is HTML-escaped to "&gt;" above)
        if (/^&gt;\s?/.test(trimmed)) {
            flushAll();
            const quoted = [];
            while (i < lines.length && /^&gt;\s?/.test(lines[i].trim())) {
                quoted.push(_inlineMarkdown(lines[i].trim().replace(/^&gt;\s?/, '')));
                i++;
            }
            html += `<blockquote>${quoted.join('<br>')}</blockquote>`;
            continue;
        }

        // Lists (nested levels are flattened)
        const item = line.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
        if (item) {
            flushPara();
            const type = /\d/.test(item[2]) ? 'ol' : 'ul';
            if (listType && listType !== type) flushList();
            listType = type;
            listItems.push(`<li>${_inlineMarkdown(item[3])}</li>`);
            i++;
            continue;
        }

        flushList();
        para.push(_inlineMarkdown(trimmed));
        i++;
    }

    flushAll();
    return html;
}

function _fillAiForm(entry) {
    document.getElementById('aiBaseUrl').value = entry ? entry.base_url : '';
    document.getElementById('aiModel').value = entry ? entry.model : '';
    document.getElementById('aiTemperature').value = entry ? entry.temperature : 0.7;

    const keyInput = document.getElementById('aiApiKey');
    keyInput.value = '';
    keyInput.placeholder = entry && entry.has_key ? '已保存，留空不修改' : 'sk-...';
}

function _applyAiConfig(cfg) {
    _aiConfig = cfg;
    const models = cfg.models || [];

    // Reuse locally saved models first; only offer "new" when needed
    const sel = document.getElementById('aiModelSelect');
    sel.innerHTML = models.map(m =>
        `<option value="${escapeHtml(m.id)}">${escapeHtml(m.model)} · ${escapeHtml(m.base_url)}</option>`
    ).join('') + '<option value="__new__">＋ 新增模型</option>';
    sel.value = cfg.active ? cfg.active.id : '__new__';

    _fillAiForm(cfg.active);
    _aiConfigured = !!cfg.active;
    document.getElementById('aiConfigSummary').textContent = models.length
        ? `本地已保存 ${models.length} 个，当前：${cfg.active ? cfg.active.model : '无'}`
        : '未配置';
    // Open the config panel on first use
    document.getElementById('aiConfigBox').open = !_aiConfigured;
}

async function onAiModelSelectChange() {
    const sel = document.getElementById('aiModelSelect');
    if (sel.value === '__new__') {
        _fillAiForm(null);
        _aiSetStatus('aiConfigStatus', '填写后点「保存配置」即可新增模型');
        return;
    }

    const entry = ((_aiConfig && _aiConfig.models) || []).find(m => m.id === sel.value);
    if (!entry) return;
    _fillAiForm(entry);
    try {
        _applyAiConfig(await apiPost('/api/ai/config/active', { id: entry.id }));
        _aiSetStatus('aiConfigStatus', `已切换到 ${entry.model}`);
    } catch (e) {
        _aiSetStatus('aiConfigStatus', '切换失败: ' + e.message, true);
    }
}

async function openAiModal() {
    const conv = state.conversations.find(c => c.cid === state.currentCid);
    document.getElementById('aiConvTitle').textContent = conv
        ? `· ${conv.title}` : '· 未选择会话';
    document.getElementById('aiModal').style.display = 'flex';

    try {
        _applyAiConfig(await apiGet('/api/ai/config'));
    } catch (e) {
        _aiSetStatus('aiConfigStatus', '读取配置失败: ' + e.message, true);
    }
}

async function saveAiConfig() {
    const body = {
        base_url: document.getElementById('aiBaseUrl').value.trim(),
        model: document.getElementById('aiModel').value.trim(),
        temperature: parseFloat(document.getElementById('aiTemperature').value) || 0,
    };
    const key = document.getElementById('aiApiKey').value.trim();
    if (key) body.api_key = key;

    _aiSetStatus('aiConfigStatus', '保存中...');
    try {
        _applyAiConfig(await apiPost('/api/ai/config', body));
        _aiSetStatus('aiConfigStatus', '已保存并设为当前模型');
        return true;
    } catch (e) {
        _aiSetStatus('aiConfigStatus', '保存失败: ' + e.message, true);
        return false;
    }
}

async function testAiConnection() {
    const btn = document.getElementById('aiTestBtn');
    btn.disabled = true;
    try {
        // Persist the form first so a newly typed model can be tested
        if (!(await saveAiConfig())) return;
        _aiSetStatus('aiConfigStatus', '测试中...');
        const data = await apiPost('/api/ai/test');
        _aiSetStatus('aiConfigStatus', '连接成功：' + (data.reply || 'OK').substring(0, 80));
    } catch (e) {
        _aiSetStatus('aiConfigStatus', '连接失败: ' + e.message, true);
    } finally {
        btn.disabled = false;
    }
}

async function runAiAnalyze() {
    if (!state.currentCid) {
        _aiSetStatus('aiStatus', '请先在左侧选择一个会话', true);
        return;
    }
    const prompt = document.getElementById('aiPrompt').value.trim();
    if (!prompt) {
        _aiSetStatus('aiStatus', '请输入分析要求', true);
        return;
    }

    const btn = document.getElementById('aiRunBtn');
    const answerEl = document.getElementById('aiAnswer');
    const thinkBox = document.getElementById('aiThinking');
    const thinkBody = document.getElementById('aiThinkingBody');
    const thinkState = document.getElementById('aiThinkingState');

    btn.disabled = true;
    btn.textContent = '分析中...';
    answerEl.innerHTML = '';
    thinkBox.style.display = 'none';
    thinkBox.open = true;
    thinkBody.textContent = '';
    thinkState.textContent = '';
    _aiSetStatus('aiStatus', '正在连接模型...');

    const started = Date.now();
    const timer = setInterval(() => {
        _aiSetStatus('aiStatus',
            `分析中… ${Math.round((Date.now() - started) / 1000)}s`);
    }, 1000);

    let reasoning = '';
    let content = '';
    let metaText = '';
    let failed = null;
    let renderTimer = null;

    const renderLater = () => {
        if (renderTimer) return;
        renderTimer = setTimeout(() => {
            renderTimer = null;
            answerEl.innerHTML = renderAiMarkdown(content);
        }, 80);
    };

    try {
        const resp = await fetch('/api/ai/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                cid: state.currentCid,
                prompt: prompt,
                limit: parseInt(document.getElementById('aiMsgLimit').value, 10) || 300,
            }),
        });
        if (!resp.ok) throw await _apiError(resp);
        if (!resp.body) throw new Error('浏览器不支持流式读取');

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            let sep;
            while ((sep = buffer.indexOf('\n\n')) >= 0) {
                const frame = buffer.slice(0, sep);
                buffer = buffer.slice(sep + 2);

                for (const line of frame.split('\n')) {
                    if (!line.startsWith('data:')) continue;
                    const raw = line.slice(5).trim();
                    if (!raw) continue;

                    let ev;
                    try { ev = JSON.parse(raw); } catch (e) { continue; }

                    if (ev.type === 'meta') {
                        metaText = `${ev.model} · 使用 ${ev.messages_used}/${ev.messages_total} 条消息`;
                    } else if (ev.type === 'reasoning') {
                        reasoning += ev.text;
                        thinkBox.style.display = '';
                        thinkState.textContent = `${reasoning.length} 字`;
                        thinkBody.textContent = reasoning;
                        thinkBody.scrollTop = thinkBody.scrollHeight;
                    } else if (ev.type === 'content') {
                        content += ev.text;
                        renderLater();
                    } else if (ev.type === 'error') {
                        failed = ev.message || '未知错误';
                    }
                }
            }
        }

        if (renderTimer) {
            clearTimeout(renderTimer);
            renderTimer = null;
        }
        answerEl.innerHTML = content ? renderAiMarkdown(content) : '';

        if (failed) {
            _aiSetStatus('aiStatus', '分析失败: ' + failed, true);
        } else if (!content) {
            _aiSetStatus('aiStatus', '模型未返回内容', true);
        } else {
            _aiSetStatus('aiStatus', metaText);
        }
    } catch (e) {
        _aiSetStatus('aiStatus', '分析失败: ' + e.message, true);
    } finally {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = '开始分析';
        if (!reasoning) thinkBox.style.display = 'none';
    }
}

// --- AI analysis history ---

async function openAiHistory() {
    document.getElementById('aiHistoryModal').style.display = 'flex';
    await loadAiHistory();
}

async function loadAiHistory() {
    const box = document.getElementById('aiHistoryList');
    box.innerHTML = '<div class="loading">加载中...</div>';
    try {
        const data = await apiGet('/api/ai/history?limit=200');
        const records = data.records || [];
        document.getElementById('aiHistoryCount').textContent =
            records.length ? `· 共 ${records.length} 条` : '';
        if (!records.length) {
            box.innerHTML = '<div class="loading">暂无分析记录</div>';
            return;
        }
        box.innerHTML = records.map(r => `
            <div class="ai-history-item">
                <div class="ai-history-head">
                    <span class="ai-history-title">${escapeHtml(r.title || r.cid)}</span>
                    <span class="ai-history-meta">${escapeHtml(r.created_at || '')} · ${escapeHtml(r.model || '')}</span>
                    <button class="ai-history-del" data-id="${escapeHtml(r.id)}" title="删除这条记录">&times;</button>
                </div>
                <div class="ai-history-prompt">${escapeHtml(r.prompt || '')}</div>
                <details class="ai-history-answer">
                    <summary>查看分析结果</summary>
                    <div class="ai-answer ai-history-body">${renderAiMarkdown(r.answer || '')}</div>
                </details>
            </div>`).join('');
    } catch (e) {
        box.innerHTML = `<div class="loading">读取失败: ${escapeHtml(e.message)}</div>`;
    }
}

async function deleteAiHistory(id) {
    try {
        const resp = await fetch(`${API_BASE}/api/ai/history/${encodeURIComponent(id)}`,
            { method: 'DELETE' });
        if (!resp.ok) throw await _apiError(resp);
        await loadAiHistory();
    } catch (e) {
        document.getElementById('aiHistoryCount').textContent = `· 删除失败: ${e.message}`;
    }
}

// --- Lightbox ---

function openLightbox(src) {
    document.getElementById('lightboxImg').src = src;
    document.getElementById('lightbox').style.display = 'flex';
}

// --- Event bindings ---

function init() {
    // Fetch current user UID
    apiGet('/api/config').then(data => {
        state.myUid = String(data.user_uid || '');
    }).catch(() => {});

    // Load conversations
    loadConversations(true);
    loadSyncStatus();

    // Sidebar: conversation search
    document.getElementById('convSearchInput').addEventListener('input', e => {
        _convSearch = e.target.value.trim();
        renderConversations(_convTotal);
    });

    // Sidebar: type filter tabs
    document.querySelectorAll('.sidebar-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            _convFilter = tab.dataset.filter;
            renderConversations(_convTotal);
        });
    });

    // Message search
    document.getElementById('searchBtn').addEventListener('click', doSearch);
    document.getElementById('searchInput').addEventListener('keydown', e => {
        if (e.key === 'Enter') doSearch();
    });

    // Close search
    document.getElementById('searchCloseBtn').addEventListener('click', () => {
        document.getElementById('searchView').style.display = 'none';
        if (state.currentCid) {
            document.getElementById('messageView').style.display = 'flex';
        } else {
            document.getElementById('emptyState').style.display = 'flex';
        }
    });

    // Sync
    document.getElementById('syncBtn').addEventListener('click', triggerSync);

    // Exports
    document.getElementById('exportBtn').addEventListener('click', () => {
        document.getElementById('exportModal').style.display = 'flex';
        _exportSelected = {};
        _exportFilter = 'all';
        document.querySelectorAll('#exportFilterTabs .sidebar-tab').forEach(t => t.classList.toggle('active', t.dataset.filter === 'all'));
        loadExportConvList();
        loadExports();
        // Reset to select tab
        document.querySelectorAll('.export-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'select'));
        document.getElementById('exportPanelSelect').style.display = '';
        document.getElementById('exportPanelFiles').style.display = 'none';
    });
    document.getElementById('exportModalClose').addEventListener('click', () => {
        document.getElementById('exportModal').style.display = 'none';
    });

    // Export tab switching
    document.querySelectorAll('.export-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.export-tab').forEach(t => t.classList.toggle('active', t === tab));
            document.getElementById('exportPanelSelect').style.display = tab.dataset.tab === 'select' ? '' : 'none';
            document.getElementById('exportPanelFiles').style.display = tab.dataset.tab === 'files' ? '' : 'none';
        });
    });

    // Select all checkbox
    document.getElementById('selectAllCbs').addEventListener('change', e => {
        const checked = e.target.checked;
        const keyword = document.getElementById('exportSearchInput').value.trim().toLowerCase();
        let filtered = _exportAllConvs;
        if (keyword) {
            filtered = filtered.filter(c => (c.title || '').toLowerCase().includes(keyword));
        }
        filtered.forEach(c => { _exportSelected[c.cid] = checked; });
        renderExportConvList(document.getElementById('exportSearchInput').value.trim());
    });

    // Export type filter tabs
    document.querySelectorAll('#exportFilterTabs .sidebar-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('#exportFilterTabs .sidebar-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            _exportFilter = tab.dataset.filter;
            renderExportConvList(document.getElementById('exportSearchInput').value.trim());
        });
    });

    // Search in export modal
    document.getElementById('exportSearchInput').addEventListener('input', e => {
        renderExportConvList(e.target.value.trim());
    });

    // Export selected conversations
    document.getElementById('exportSelectedBtn').addEventListener('click', async () => {
        const cids = Object.entries(_exportSelected).filter(([_, v]) => v).map(([k]) => k);
        if (cids.length === 0) return;

        const btn = document.getElementById('exportSelectedBtn');
        btn.disabled = true;
        btn.textContent = '导出中...';

        // Calculate since_time from selected time range
        const months = parseInt(document.getElementById('exportTimeRange').value);
        let sinceTime = null;
        if (months > 0) {
            sinceTime = Date.now() - months * 30 * 24 * 3600 * 1000;
        }

        try {
            await fetch('/api/export/selected', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cids, since_time: sinceTime }),
            });

            // Poll for completion
            const poll = setInterval(async () => {
                try {
                    const s = await apiGet('/api/sync/status');
                    if (!s.is_syncing) {
                        clearInterval(poll);
                        btn.disabled = false;
                        btn.textContent = '导出选中会话';
                        // Switch to files tab and refresh
                        document.querySelectorAll('.export-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'files'));
                        document.getElementById('exportPanelSelect').style.display = 'none';
                        document.getElementById('exportPanelFiles').style.display = '';
                        loadExports();
                    }
                } catch (e) {}
            }, 2000);
        } catch (e) {
            btn.disabled = false;
            btn.textContent = '导出选中会话';
            alert('导出失败: ' + e.message);
        }
    });

    // Full export
    document.getElementById('fullExportBtn').addEventListener('click', async () => {
        const btn = document.getElementById('fullExportBtn');
        const progress = document.getElementById('exportProgress');
        btn.disabled = true;
        progress.textContent = '正在触发全量导出...';

        try {
            await apiPost('/api/sync/trigger?full=true');
            const poll = setInterval(async () => {
                try {
                    const s = await apiGet('/api/sync/status');
                    if (!s.is_syncing) {
                        clearInterval(poll);
                        btn.disabled = false;
                        progress.textContent = s.last_export_path ? '导出完成' : '同步完成';
                        loadExports();
                        setTimeout(() => { progress.textContent = ''; }, 5000);
                    } else {
                        progress.textContent = '导出中，请稍候...';
                    }
                } catch (e) {}
            }, 3000);
        } catch (e) {
            btn.disabled = false;
            progress.textContent = '导出失败: ' + e.message;
        }
    });

    // AI analysis
    document.getElementById('aiBtn').addEventListener('click', openAiModal);
    document.getElementById('aiModalClose').addEventListener('click', () => {
        document.getElementById('aiModal').style.display = 'none';
    });
    document.getElementById('aiSaveBtn').addEventListener('click', saveAiConfig);
    document.getElementById('aiTestBtn').addEventListener('click', testAiConnection);
    document.getElementById('aiModelSelect').addEventListener('change', onAiModelSelectChange);
    document.getElementById('aiRunBtn').addEventListener('click', runAiAnalyze);
    document.querySelectorAll('.ai-presets button').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('aiPrompt').value = btn.dataset.prompt;
            document.getElementById('aiPrompt').focus();
        });
    });
    document.getElementById('aiPrompt').addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') runAiAnalyze();
    });

    // AI analysis history
    document.getElementById('aiHistoryBtn').addEventListener('click', openAiHistory);
    document.getElementById('aiHistoryClose').addEventListener('click', () => {
        document.getElementById('aiHistoryModal').style.display = 'none';
    });
    document.getElementById('aiHistoryList').addEventListener('click', e => {
        const btn = e.target.closest('.ai-history-del');
        if (btn) deleteAiHistory(btn.dataset.id);
    });

    // Lightbox
    document.getElementById('lightboxClose').addEventListener('click', () => {
        document.getElementById('lightbox').style.display = 'none';
    });
    document.getElementById('lightbox').addEventListener('click', e => {
        if (e.target === e.currentTarget) {
            document.getElementById('lightbox').style.display = 'none';
        }
    });

    // Refresh sync status periodically
    setInterval(loadSyncStatus, 60000);
}

// Make functions global for onclick handlers
window.goToPage = goToPage;
window.openLightbox = openLightbox;

document.addEventListener('DOMContentLoaded', init);
