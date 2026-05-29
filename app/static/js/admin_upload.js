(function () {
  const hasUploadSupport = !!(window.XMLHttpRequest && window.FormData);

  function ensureProgressModal() {
    let modal = document.getElementById('upload-progress-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'upload-progress-modal';
    modal.className = 'upload-progress-modal';
    modal.innerHTML = `
      <div class="upload-progress-card" role="dialog" aria-modal="true" aria-labelledby="upload-progress-title">
        <div class="upload-progress-icon"><i class="bi bi-cloud-arrow-up"></i></div>
        <h2 id="upload-progress-title">Enviando arquivo...</h2>
        <p id="upload-progress-text">Preparando upload</p>
        <div class="upload-progress-track"><span id="upload-progress-bar"></span></div>
        <strong id="upload-progress-percent">0%</strong>
        <small>Não feche esta página até o envio terminar.</small>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  function setProgress(percent, text) {
    const modal = ensureProgressModal();
    const bar = modal.querySelector('#upload-progress-bar');
    const pct = modal.querySelector('#upload-progress-percent');
    const label = modal.querySelector('#upload-progress-text');
    const safePercent = Math.max(0, Math.min(100, Math.round(percent || 0)));

    modal.classList.add('show');
    bar.style.width = safePercent + '%';
    pct.textContent = safePercent + '%';
    if (text) label.textContent = text;
  }

  function setModalState(title, text, stateClass) {
    const modal = ensureProgressModal();
    const card = modal.querySelector('.upload-progress-card');
    modal.classList.add('show');
    card.classList.remove('is-error', 'is-success');
    if (stateClass) card.classList.add(stateClass);
    modal.querySelector('#upload-progress-title').textContent = title;
    modal.querySelector('#upload-progress-text').textContent = text;
  }

  function formHasSelectedFile(form) {
    return Array.from(form.querySelectorAll('input[type="file"]')).some(input => input.files && input.files.length > 0);
  }

  function isUploadForm(form) {
    const enctype = (form.getAttribute('enctype') || '').toLowerCase();
    return enctype.includes('multipart/form-data') || !!form.querySelector('input[type="file"]');
  }

  function disableForm(form, disabled) {
    form.querySelectorAll('button, input, textarea, select').forEach(el => {
      if (disabled) {
        if (!el.dataset.wasDisabled) el.dataset.wasDisabled = el.disabled ? '1' : '0';
        el.disabled = true;
      } else if (el.dataset.wasDisabled === '0') {
        el.disabled = false;
      }
    });
  }

  document.addEventListener('submit', function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!hasUploadSupport || !isUploadForm(form) || !formHasSelectedFile(form)) return;

    event.preventDefault();

    const xhr = new XMLHttpRequest();
    const formData = new FormData(form);
    const method = (form.getAttribute('method') || 'POST').toUpperCase();
    const action = form.getAttribute('action') || window.location.href;

    disableForm(form, true);
    setProgress(0, 'Iniciando upload...');

    xhr.upload.addEventListener('progress', function (e) {
      if (!e.lengthComputable) {
        setProgress(5, 'Enviando arquivo...');
        return;
      }
      const percent = (e.loaded / e.total) * 100;
      const loadedMb = (e.loaded / 1024 / 1024).toFixed(1);
      const totalMb = (e.total / 1024 / 1024).toFixed(1);
      setProgress(percent, `${loadedMb} MB de ${totalMb} MB enviados`);
    });

    xhr.addEventListener('load', function () {
      if (xhr.status >= 200 && xhr.status < 400) {
        setProgress(100, 'Upload concluído. Salvando alterações...');
        setModalState('Upload concluído', 'Atualizando painel...', 'is-success');
        setTimeout(function () {
          if (xhr.responseText && xhr.responseText.includes('<!doctype html')) {
            document.open();
            document.write(xhr.responseText);
            document.close();
            if (xhr.responseURL) history.replaceState(null, '', xhr.responseURL);
          } else {
            window.location.href = xhr.responseURL || window.location.href;
          }
        }, 450);
      } else {
        disableForm(form, false);
        setModalState('Erro no upload', 'O servidor retornou erro ' + xhr.status + '. Tente novamente.', 'is-error');
      }
    });

    xhr.addEventListener('error', function () {
      disableForm(form, false);
      setModalState('Falha na conexão', 'Não foi possível concluir o envio. Verifique a internet e tente novamente.', 'is-error');
    });

    xhr.addEventListener('abort', function () {
      disableForm(form, false);
      setModalState('Upload cancelado', 'O envio foi interrompido antes de terminar.', 'is-error');
    });

    xhr.open(method, action, true);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.send(formData);
  }, true);
})();
