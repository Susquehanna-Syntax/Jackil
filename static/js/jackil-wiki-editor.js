// The wiki editor: live preview, a Markdown toolbar, Ctrl/Cmd+S, attachments.
//
// Preview goes through POST /wiki/preview/ — the same renderer that paints the
// saved page — so what a writer sees is what a reader gets, KaTeX included.

const PREVIEW_URL = '/wiki/preview/';
const PREVIEW_DEBOUNCE_MS = 300;

// Toolbar buttons. data-wiki-md is what the click handler finds with closest();
// data-wiki-insert is "wrap:before|after", "line:prefix", or text to drop at the
// cursor. A wrap states its kind because a bare "|" — a table's cell delimiter —
// would otherwise be read as the wrap separator, and Page link needs one to wrap
// [[ ]]: its payload is "wrap:[[|]]".
const WIKI_BUTTONS = [
  ['Bold', 'bold', 'wrap:**|**'],
  ['Italic', 'italic', 'wrap:_|_'],
  ['Heading', 'heading', 'line:## '],
  ['Link', 'link', 'wrap:[|](https://)'],
  ['Code block', 'code-block', '```\ncode\n```'],
  ['Table', 'table', '| A | B |\n|---|---|\n| | |'],
  ['Task', 'task', 'line:- [ ] '],
  ['Math', 'math', 'wrap:$|$'],
  ['Callout', 'callout', '> [!NOTE]\n> '],
  ['Page link', 'page-link', 'wrap:[[|]]'],
];

function wikiToolbarMarkup() {
  return WIKI_BUTTONS.map(function (b) {
    const label = b[0];
    return (
      '<button type="button" data-wiki-md="' + b[1] + '" data-wiki-insert="' + escAttr(b[2]) +
      '" title="' + escAttr(label) + '" aria-label="' + escAttr(label) + '">' +
      escHtml(label) + '</button>'
    );
  }).join('');
}

function afterWikiEdit(textarea, caret, selectionEnd) {
  textarea.focus();
  textarea.selectionStart = caret;
  textarea.selectionEnd = selectionEnd;
  // The preview listens for input; a script that changes the value has to say so.
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

// Wraps the selection, or drops the pair at the cursor with the caret inside it.
// The payload is read back off the element by getAttribute and so arrives already
// entity-decoded; "[[|]]" splits into before="[[" / after="]]" and nothing else.
function insertAround(textarea, before, after) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const placeholder = 'text';
  const selected = textarea.value.slice(start, end);
  // A wrap on an empty selection leaves the caret between the markers to type in:
  // Bold gives "**|**", Math "$|$", a page link "[[|]]" — the cursor sits inside.
  const body = selected || placeholder;
  textarea.value =
    textarea.value.slice(0, start) + before + body + after + textarea.value.slice(end);
  const caret = start + before.length;
  afterWikiEdit(textarea, selected ? caret : caret + body.length, caret + body.length);
}

// Line prefixes (headings, tasks, callouts) belong to the line, not to the caret.
function insertAtLineStart(textarea, prefix) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const bol = textarea.value.lastIndexOf('\n', start - 1) + 1;
  textarea.value = textarea.value.slice(0, bol) + prefix + textarea.value.slice(bol);
  afterWikiEdit(textarea, start + prefix.length, Math.max(start + prefix.length, end + prefix.length));
}

// A browser hands a textarea's value back with the platform's line ending, so a
// block insert written as bare \n can come back glued or mixed. Writing CRLF is
// what the element itself would produce for a multi-line paste.
function withCrlf(text) {
  return text.replace(/\r\n/g, '\n').replace(/\n/g, '\r\n');
}

function insertAtCursor(textarea, text) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const beforeText = textarea.value.slice(0, start);
  // Tables and callouts are blocks: they get a blank line before them rather
  // than being spliced into the middle of a sentence.
  let piece = text;
  if (text.indexOf('\n') !== -1) {
    if (beforeText !== '' && !beforeText.endsWith('\n')) piece += '\n';
    if (beforeText !== '' && !beforeText.endsWith('\n\n')) {
      piece = (beforeText.endsWith('\n') ? '\n' : '\n\n') + piece;
    }
    piece = withCrlf(piece);
  }
  textarea.value = textarea.value.slice(0, start) + piece + textarea.value.slice(end);
  afterWikiEdit(textarea, start + piece.length, start + piece.length);
}

// Attachment Markdown arrives one file at a time and always sits alone on a line.
function insertAttachmentLine(textarea, text) {
  const start = textarea.selectionStart;
  const beforeText = textarea.value.slice(0, start);
  const lead = beforeText === '' || beforeText.endsWith('\n') ? '' : '\n';
  const piece = lead + text.replace(/\s*\n\s*/g, ' ') + '\n';
  textarea.value = beforeText + piece + textarea.value.slice(textarea.selectionEnd);
  afterWikiEdit(textarea, start + piece.length, start + piece.length);
}

function applyWikiInsert(textarea, spec) {
  if (spec.indexOf('line:') === 0) {
    insertAtLineStart(textarea, spec.slice('line:'.length));
  } else if (spec.indexOf('wrap:') === 0) {
    const parts = spec.slice('wrap:'.length).split('|');
    insertAround(textarea, parts[0], parts[1]);
  } else {
    insertAtCursor(textarea, spec);
  }
}

function showPreviewError(pane, message) {
  pane.innerHTML = '<p class="muted-note">Preview unavailable: ' + escHtml(message) + '</p>';
}

// Keystrokes arrive faster than the server answers, so each response checks a
// counter for whether anything typed since it left has already made it stale.
function startLivePreview(textarea, pane) {
  let latest = 0;
  let timer = null;

  textarea.addEventListener('input', function () {
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      const seq = ++latest;
      apiJson(PREVIEW_URL, { method: 'POST', body: JSON.stringify({ body: textarea.value }) })
        .then(function (data) {
          if (seq !== latest) return;
          pane.innerHTML = data.html || '';
          renderMath(pane);
        })
        .catch(function (err) {
          if (seq !== latest) return;
          showPreviewError(pane, err.message || 'the preview could not be rendered');
        });
    }, PREVIEW_DEBOUNCE_MS);
  });
}

// Uploads finish long after the click that started them, and drop their Markdown
// at whatever the caret has become by then — so the textarea is module state.
let wikiTextarea = null;

function uploadAttachments(attachUrl, files) {
  const form = new FormData();
  Array.prototype.forEach.call(files, function (f) { form.append('files', f); });
  return fetch(attachUrl, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-CSRFToken': getCsrf() },
    body: form,
  })
    .then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (body) {
        if (!resp.ok) throw new Error(body.error || 'Upload failed');
        return body;
      });
    })
    .then(function (body) {
      const uploaded = (body && body.files) || [];
      let attached = 0;
      for (let i = 0; i < uploaded.length; i++) {
        if (!uploaded[i] || !uploaded[i].markdown) continue;
        if (wikiTextarea) insertAttachmentLine(wikiTextarea, uploaded[i].markdown);
        attached += 1;
      }
      if (attached) showToast(attached === 1 ? 'File attached' : attached + ' files attached', 'ok');
      return attached;
    })
    .catch(function (err) {
      showToast(err.message || 'Upload failed', 'error');
      return 0;
    });
}

// Files ride a paste or a drop in more than one place: a screenshot lands on the
// items list, an attached document in clipboardData.files.
function filesInTransfer(transfer) {
  if (!transfer) return [];
  const picked = [];
  if (transfer.files) {
    for (let i = 0; i < transfer.files.length; i++) picked.push(transfer.files[i]);
  }
  if (picked.length === 0 && transfer.items) {
    for (let i = 0; i < transfer.items.length; i++) {
      const item = transfer.items[i];
      if (item.kind === 'file' && typeof item.getAsFile === 'function') {
        const f = item.getAsFile();
        if (f) picked.push(f);
      }
    }
  }
  return picked;
}

document.addEventListener('DOMContentLoaded', function () {
  const form = document.querySelector('form[data-wiki-editor]');
  if (!form) return;
  const textarea = form.querySelector('textarea[name="body"]');
  if (!textarea) return;
  const pane = form.querySelector('.wiki-preview[data-markdown]');
  const attachUrl = form.getAttribute('data-attach-url');

  wikiTextarea = textarea;

  const toolbar = form.querySelector('.wiki-toolbar');
  if (toolbar) {
    toolbar.innerHTML = wikiToolbarMarkup();
    toolbar.removeAttribute('aria-hidden');
    toolbar.addEventListener('click', function (event) {
      const button = event.target.closest('[data-wiki-md]');
      if (!button) return;
      event.preventDefault();
      applyWikiInsert(textarea, button.getAttribute('data-wiki-insert') || '');
    });
  }

  if (pane) startLivePreview(textarea, pane);

  const initial = textarea.value;
  let submitting = false;
  form.addEventListener('submit', function () { submitting = true; });
  window.addEventListener('beforeunload', function (event) {
    if (submitting || textarea.value === initial) return;
    event.preventDefault();
    event.returnValue = '';
  });

  document.addEventListener('keydown', function (event) {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key !== 's' && event.key !== 'S') return;
    event.preventDefault();
    if (typeof form.requestSubmit === 'function') form.requestSubmit();
    else form.submit();
  });

  const attach = form.querySelector('[data-wiki-attach]');
  const fileInput = form.querySelector('[data-wiki-files]');
  if (!attach || !fileInput) return;

  // A brand-new page has no row to hang a file on yet.
  if (!attachUrl) {
    attach.disabled = true;
    attach.setAttribute('title', 'Save the page first to attach files');
    return;
  }

  attach.addEventListener('click', function () { fileInput.click(); });
  fileInput.addEventListener('change', function () {
    const picked = Array.prototype.slice.call(fileInput.files || []);
    fileInput.value = '';
    if (picked.length) uploadAttachments(attachUrl, picked);
  });
  textarea.addEventListener('paste', function (event) {
    const pasted = filesInTransfer(event.clipboardData);
    if (!pasted.length) return;
    event.preventDefault();
    uploadAttachments(attachUrl, pasted);
  });
  ['dragenter', 'dragover'].forEach(function (name) {
    textarea.addEventListener(name, function (event) {
      if (filesInTransfer(event.dataTransfer).length) event.preventDefault();
    });
  });
  textarea.addEventListener('drop', function (event) {
    const dropped = filesInTransfer(event.dataTransfer);
    if (!dropped.length) return;
    event.preventDefault();
    uploadAttachments(attachUrl, dropped);
  });
});
