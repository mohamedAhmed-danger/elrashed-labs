/**
 * static/js/test_service.js
 * Clean vanilla JavaScript handling AI Auto-generation, manual Generate/Regenerate,
 * and Tag/Chip management for the Laboratory Test Service create/edit workflow.
 */

document.addEventListener('DOMContentLoaded', () => {
  initTestFormWorkflow();
});

function initTestFormWorkflow() {
  const form = document.getElementById('testForm');
  if (!form) return;

  const isEditMode = form.dataset.isEdit === 'true';
  const nameInput = document.getElementById('testNameInput');
  const priceInput = document.getElementById('testPriceInput');
  const durationInput = document.getElementById('testDurationInput');
  const sampleInput = document.getElementById('testSampleTypeInput');
  const generateBtn = document.getElementById('generateBtn');
  const regenerateBtn = document.getElementById('regenerateBtn');

  // Tag inputs
  initTagInput('keywordsContainer', 'keywordsTextInput', 'keywords');
  initTagInput('aliasesContainer', 'aliasesTextInput', 'alias_name');

  // Track the last text used for generation to avoid redundant calls
  let lastGeneratedName = (nameInput && nameInput.value) ? nameInput.value.trim() : '';
  let isGenerating = false;
  let debounceTimer = null;

  // Smart condition for Auto-Generation
  function canTriggerAutoGenerate() {
    if (isEditMode) return false;
    
    const name = nameInput ? nameInput.value.trim() : '';
    const price = priceInput ? priceInput.value.trim() : '';
    const duration = durationInput ? durationInput.value.trim() : '';
    const sample = sampleInput ? sampleInput.value.trim() : '';

    // 1. Name (>3 chars) and Price are strictly required
    const hasCoreRequirements = name.length >= 3 && price !== '' && parseFloat(price) > 0;
    
    // 2. If the user manually wrote duration or sample type, skip auto-generation to respect manual input
    const userWroteExtra = duration !== '' || sample !== '';

    return hasCoreRequirements && !userWroteExtra && name !== lastGeneratedName && !isGenerating;
  }

  // 1. Automatic AI Generation on Test Name & Price Input (Create Mode only)
  if (!isEditMode && nameInput && priceInput) {
    const handleAutoTrigger = () => {
      clearTimeout(debounceTimer);
      if (canTriggerAutoGenerate()) {
        debounceTimer = setTimeout(() => {
          if (canTriggerAutoGenerate()) {
            triggerGenerate(true);
          }
        }, 2000); // 2 seconds delay after user stops typing
      }
    };

    nameInput.addEventListener('input', handleAutoTrigger);
    priceInput.addEventListener('input', handleAutoTrigger);

    // Cancel timer if user starts typing custom duration or sample type
    if (durationInput) durationInput.addEventListener('input', () => clearTimeout(debounceTimer));
    if (sampleInput) sampleInput.addEventListener('input', () => clearTimeout(debounceTimer));
  }

  // 2. Manual "Generate with AI" button
  if (generateBtn) {
    generateBtn.addEventListener('click', (e) => {
      e.preventDefault();
      triggerGenerate(false);
    });
  }

  // 3. Manual "Regenerate" button
  if (regenerateBtn) {
    regenerateBtn.addEventListener('click', (e) => {
      e.preventDefault();
      triggerRegenerate();
    });
  }

  // 4. Ensure any typed tag is saved when form is submitted
  form.addEventListener('submit', () => {
    commitPendingTag('keywordsContainer', 'keywordsTextInput', 'keywords');
    commitPendingTag('aliasesContainer', 'aliasesTextInput', 'alias_name');
  });

  // ── Generation Function ─────────────────────────────────────
  async function triggerGenerate(isAuto = false) {
    if (isGenerating) return;

    const name = nameInput ? nameInput.value.trim() : '';
    const price = priceInput ? priceInput.value.trim() : '';

    if (!name) {
      if (!isAuto) {
        showStatus('error', 'يرجى إدخال اسم التحليل الطبي أولاً لتوليد البيانات.');
        if (nameInput) nameInput.focus();
      }
      return;
    }

    if (!price && !isAuto) {
      showStatus('error', 'يرجى إدخال سعر التحليل الطبي أولاً.');
      if (priceInput) priceInput.focus();
      return;
    }

    isGenerating = true;
    lastGeneratedName = name;
    setButtonsLoading(true, 'generate');
    showStatus('loading', 'جاري توليد معلومات التحليل بالذكاء الاصطناعي...');

    try {
      const payload = {
        name: name,
        price: price ? parseFloat(price) : null,
        duration: durationInput ? durationInput.value.trim() : '',
        sample_type: sampleInput ? sampleInput.value.trim() : '',
        description: document.getElementById('testDescriptionInput')?.value || '',
        patient_instructions: document.getElementById('testInstructionsInput')?.value || '',
      };

      const response = await fetch('/tests/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'حدث خطأ أثناء توليد البيانات.');
      }

      // Populate AI fields directly into the form
      populateFormWithAIData(data);

      showStatus(
        'success',
        isAuto
          ? 'تم اقتراح بيانات التحليل تلقائياً بواسطة الذكاء الاصطناعي.'
          : 'تم توليد البيانات بنجاح. يمكنك التعديل عليها واعتمادها قبل الحفظ.'
      );
    } catch (err) {
      showStatus('error', err.message || 'تعذر الاتصال بالخادم لتوليد البيانات.');
    } finally {
      isGenerating = false;
      setButtonsLoading(false, 'generate');
    }
  }

  // ── Regeneration Function ───────────────────────────────────
  async function triggerRegenerate() {
    if (isGenerating) return;

    const name = nameInput ? nameInput.value.trim() : '';
    if (!name) {
      showStatus('error', 'يرجى إدخال اسم التحليل الطبي أولاً.');
      if (nameInput) nameInput.focus();
      return;
    }

    isGenerating = true;
    setButtonsLoading(true, 'regenerate');
    showStatus('loading', 'جاري إعادة صياغة واقتراح المعلومات بصيغة بديلة...');

    try {
      const currentKeywords = getTagValues('keywordsContainer');
      const currentAliases = getTagValues('aliasesContainer');

      const payload = {
        name: name,
        price: priceInput ? parseFloat(priceInput.value.trim()) || null : null,
        previous_output: {
          description: document.getElementById('testDescriptionInput')?.value || '',
          patient_instructions: document.getElementById('testInstructionsInput')?.value || '',
          duration: durationInput ? durationInput.value.trim() : '',
          sample_type: sampleInput ? sampleInput.value.trim() : '',
          keywords: currentKeywords,
          aliases: currentAliases,
        },
      };

      const response = await fetch('/tests/regenerate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'حدث خطأ أثناء إعادة التوليد.');
      }

      // Populate with new draft
      populateFormWithAIData(data, true); // Force update fields on manual regeneration
      showStatus('success', 'تمت إعادة صياغة واقتراح البيانات بنجاح.');
    } catch (err) {
      showStatus('error', err.message || 'تعذر الاتصال بالخادم لإعادة التوليد.');
    } finally {
      isGenerating = false;
      setButtonsLoading(false, 'regenerate');
    }
  }

  // ── Populate Form with AI Data ──────────────────────────────
  function populateFormWithAIData(data, forceOverwrite = false) {
    const descInput = document.getElementById('testDescriptionInput');
    const instInput = document.getElementById('testInstructionsInput');

    if (descInput && (forceOverwrite || !descInput.value.trim()) && data.description) {
      descInput.value = data.description;
    }

    const instructions = data.patient_instructions || data.instructions;
    if (instInput && (forceOverwrite || !instInput.value.trim()) && instructions) {
      instInput.value = instructions;
    }

    // Fill duration only if empty, or if forced
    if (durationInput && (forceOverwrite || !durationInput.value.trim()) && data.duration) {
      durationInput.value = data.duration;
    }

    // Fill sample type only if empty, or if forced
    if (sampleInput && (forceOverwrite || !sampleInput.value.trim()) && data.sample_type) {
      sampleInput.value = data.sample_type;
    }

    // Set keywords
    if (data.keywords && Array.isArray(data.keywords)) {
      setTagValues('keywordsContainer', 'keywords', data.keywords);
    }

    // Set aliases
    const aliases = data.aliases || data.alias_name;
    if (aliases && Array.isArray(aliases)) {
      setTagValues('aliasesContainer', 'alias_name', aliases);
    }

    // Subtle visual feedback pulse
    [descInput, instInput, durationInput, sampleInput].forEach(el => {
      if (el) {
        el.classList.remove('ai-field-updated');
        void el.offsetWidth; // reflow
        el.classList.add('ai-field-updated');
      }
    });

    if (window.lucide) lucide.createIcons();
  }

  // ── Status Banner Helper ────────────────────────────────────
  function showStatus(type, message) {
    const box = document.getElementById('aiStatusBox');
    if (!box) return;

    box.className = `ai-status-box ${type}`;
    let iconHtml = '';

    if (type === 'loading') {
      iconHtml = '<span class="spinner"></span>';
    } else if (type === 'success') {
      iconHtml = '<i data-lucide="check-circle" style="width: 16px; height: 16px;"></i>';
    } else if (type === 'error') {
      iconHtml = '<i data-lucide="alert-circle" style="width: 16px; height: 16px;"></i>';
    }

    box.innerHTML = `${iconHtml}<span>${message}</span>`;
    box.style.display = 'flex';

    if (window.lucide) lucide.createIcons();

    if (type === 'success') {
      setTimeout(() => {
        if (box.classList.contains('success')) {
          box.style.display = 'none';
        }
      }, 5000);
    }
  }

  // ── Button Loading States ───────────────────────────────────
  function setButtonsLoading(isLoading, action) {
    if (generateBtn) {
      generateBtn.disabled = isLoading;
      if (isLoading && action === 'generate') {
        generateBtn.innerHTML = '<span class="spinner"></span> جاري التوليد...';
      } else {
        generateBtn.innerHTML = '<i data-lucide="sparkles"></i> توليد بالذكاء الاصطناعي';
      }
    }

    if (regenerateBtn) {
      regenerateBtn.disabled = isLoading;
      if (isLoading && action === 'regenerate') {
        regenerateBtn.innerHTML = '<span class="spinner"></span> جاري إعادة التوليد...';
      } else {
        regenerateBtn.innerHTML = '<i data-lucide="refresh-cw"></i> إعادة التوليد';
      }
    }

    if (window.lucide) lucide.createIcons();
  }
}

// ============================================================
// Tag / Chip Management Functions
// ============================================================

function initTagInput(containerId, textInputId, inputName) {
  const container = document.getElementById(containerId);
  const textInput = document.getElementById(textInputId);
  if (!container || !textInput) return;

  container.addEventListener('click', (e) => {
    if (!e.target.classList.contains('tag-chip-remove')) {
      textInput.focus();
    }
  });

  textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      commitPendingTag(containerId, textInputId, inputName);
    } else if (e.key === 'Backspace' && textInput.value === '') {
      const chips = container.querySelectorAll('.tag-chip');
      if (chips.length > 0) {
        chips[chips.length - 1].remove();
      }
    }
  });

  textInput.addEventListener('blur', () => {
    commitPendingTag(containerId, textInputId, inputName);
  });
}

function commitPendingTag(containerId, textInputId, inputName) {
  const textInput = document.getElementById(textInputId);
  if (!textInput) return;

  const value = textInput.value.replace(/,/g, '').trim();
  if (value) {
    addTag(containerId, inputName, value);
    textInput.value = '';
  }
}

function addTag(containerId, inputName, text) {
  const container = document.getElementById(containerId);
  if (!container || !text) return;

  const existingValues = getTagValues(containerId);
  if (existingValues.includes(text.toLowerCase())) return;

  const chip = document.createElement('span');
  chip.className = 'tag-chip';
  chip.innerHTML = `
    <span>${escapeHtml(text)}</span>
    <input type="hidden" name="${inputName}" value="${escapeHtml(text)}">
    <button type="button" class="tag-chip-remove" title="حذف">&times;</button>
  `;

  chip.querySelector('.tag-chip-remove').addEventListener('click', (e) => {
    e.stopPropagation();
    chip.remove();
  });

  const textInput = container.querySelector('.tag-input-field');
  if (textInput) {
    container.insertBefore(chip, textInput);
  } else {
    container.appendChild(chip);
  }
}

function setTagValues(containerId, inputName, tagsArray) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.querySelectorAll('.tag-chip').forEach(c => c.remove());

  tagsArray.forEach(t => {
    if (typeof t === 'string' && t.trim()) {
      addTag(containerId, inputName, t.trim());
    }
  });
}

function getTagValues(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return [];
  const inputs = container.querySelectorAll('input[type="hidden"]');
  return Array.from(inputs).map(i => i.value.trim().toLowerCase()).filter(v => v);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}