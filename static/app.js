/* AI Video Transcriber · app.js */



class VideoTranscriber {
  constructor() {
    this.currentTaskId = null;
    this.currentTask = null;
    this.eventSource = null;
    this.statusPollTimer = null;
    this.apiBase = '/api';
    this.currentLang = 'en';
    this.inputSourceMode = 'url';
    this.uiLanguages = ['en', 'ru', 'uk'];
    this.langLabels = { en: 'English', ru: 'Русский', uk: 'Українська' };
    this.htmlLangs = { en: 'en', ru: 'ru', uk: 'uk' };

    /* Smart progress simulation */
    this.sp = {
      enabled: false, current: 0, target: 15,
      lastServer: 0, interval: null, startTime: null, stage: 'preparing'
    };
    this.stageTimer = null;

    this.i18n = {
      en: {
        title: 'AI Video Transcriber',
        subtitle: 'Supports automatic transcription and AI summary for 30+ platforms',
        video_url_placeholder: 'Paste YouTube, Tiktok, Bilibili or other platform video URLs...',
        start_transcription: 'Transcribe',
        ai_settings: 'AI Settings',
        groq_transcription: 'Groq Transcription',
        groq_api_key: 'Groq API Key',
        groq_api_key_placeholder: 'gsk_...',
        groq_model: 'Groq Whisper Model',
        groq_language: 'Input Language',
        groq_language_placeholder: 'auto',
        groq_prompt: 'Groq Prompt',
        groq_prompt_placeholder: 'Names, topic, spelling...',
        include_timecodes: 'Include time codes',
        copy_text: 'Copy text',
        copied_text: 'Copied',
        save_text: 'Save',
        summary_provider: 'Summary Provider',
        model_base_url: 'Model API Base URL',
        model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API Key',
        api_key_placeholder: 'sk-...',
        fetch_models: 'Fetch',
        model_select: 'Model',
        model_default: '— use server default —',
        reasoning_effort: 'Reasoning',
        reasoning_auto: 'Auto',
        reasoning_none: 'None',
        reasoning_minimal: 'Minimal',
        reasoning_low: 'Low',
        reasoning_medium: 'Medium',
        reasoning_high: 'High',
        reasoning_xhigh: 'Extra high',
        summary_language: 'Summary Language',
        summary_prompt_label: 'Summary Prompt',
        summary_prompt_placeholder: 'Optional: tell the model how to summarize, e.g. "focus on action items and risks".',
        processing_progress: 'Processing',
        preparing: 'Preparing…',
        transcript_text: 'Transcript',
        intelligent_summary: 'AI Summary',
        translation: 'Translation',
        download_transcript: 'Transcript',
        download_translation: 'Translation',
        download_summary: 'Summary',
        download_summary_md: 'Summary MD',
        download_summary_html: 'Summary HTML',
        download_summary_txt: 'Summary TXT',
        output_format: 'Output Format',
        format_markdown: 'Markdown',
        format_html: 'HTML',
        format_txt: 'TXT',
        format_both: 'Markdown + HTML',
        generate_summary: 'Generate Summary',
        summary_waiting: 'Transcript is ready. Generate the summary when you want to send it to the summary provider.',
        generating_summary_btn: 'Generating...',
        empty_hint: 'Paste a video URL above and let AI do the heavy lifting.',
        processing: 'Processing…',
        downloading_video: 'Resolving audio URL…',
        parsing_video: 'Parsing video info…',
        transcribing_audio: 'Transcribing audio…',
        optimizing_transcript: 'Optimizing transcript…',
        generating_summary: 'Generating summary…',
        detecting_subtitles: 'Detecting subtitles…',
        subtitle_found: 'Subtitles found! Processing text…',
        no_subtitle: 'No subtitles found, resolving audio URL for Groq…',
        mode_subtitle: '⚡ Subtitle',
        mode_whisper: 'Groq URL',
        mode_groq: 'Groq URL',
        completed: 'Done!',
        error_invalid_url: 'Please enter a valid video URL',
        error_processing_failed: 'Processing failed: ',
        error_no_download: 'No file available for download',
        error_download_failed: 'Download failed: ',
        fetching_models: 'Fetching models…',
        models_loaded: (n) => `${n} models loaded`,
        models_error: 'Failed to fetch models',
      },
      ru: {
        title: 'AI видео транскрибатор',
        subtitle: 'Автоматическая транскрибация и AI-сводки для 30+ платформ',
        video_url_placeholder: 'Вставьте ссылку на YouTube, TikTok, Bilibili или другое видео...',
        start_transcription: 'Транскрибировать',
        ai_settings: 'Настройки AI',
        groq_transcription: 'Транскрибация Groq',
        groq_api_key: 'Groq API Key',
        groq_api_key_placeholder: 'gsk_...',
        groq_model: 'Модель Groq Whisper',
        groq_language: 'Язык аудио',
        groq_language_placeholder: 'auto',
        groq_prompt: 'Промпт Groq',
        groq_prompt_placeholder: 'Имена, тема, термины...',
        include_timecodes: 'Добавить таймкоды',
        copy_text: 'Копировать текст',
        copied_text: 'Скопировано',
        save_text: 'Сохранить',
        summary_provider: 'Провайдер сводки',
        model_base_url: 'Base URL API модели',
        model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API Key',
        api_key_placeholder: 'sk-...',
        fetch_models: 'Загрузить',
        model_select: 'Модель',
        model_default: '-- использовать модель сервера --',
        reasoning_effort: 'Рассуждение',
        reasoning_auto: 'Авто',
        reasoning_none: 'Нет',
        reasoning_minimal: 'Минимальное',
        reasoning_low: 'Низкое',
        reasoning_medium: 'Среднее',
        reasoning_high: 'Высокое',
        reasoning_xhigh: 'Очень высокое',
        summary_language: 'Язык сводки',
        summary_prompt_label: 'Промпт сводки',
        summary_prompt_placeholder: 'Необязательно: укажите, как делать сводку, например "сфокусируйся на действиях и рисках".',
        processing_progress: 'Обработка',
        preparing: 'Подготовка...',
        transcript_text: 'Транскрипт',
        intelligent_summary: 'AI-сводка',
        translation: 'Перевод',
        download_transcript: 'Транскрипт',
        download_translation: 'Перевод',
        download_summary: 'Сводка',
        download_summary_md: 'Сводка MD',
        download_summary_html: 'Сводка HTML',
        download_summary_txt: 'Сводка TXT',
        output_format: 'Формат вывода',
        format_markdown: 'Markdown',
        format_html: 'HTML',
        format_txt: 'TXT',
        format_both: 'Markdown + HTML',
        generate_summary: 'Создать сводку',
        summary_waiting: 'Транскрипт готов. Создайте сводку, когда будете готовы отправить его провайдеру.',
        generating_summary_btn: 'Создание...',
        empty_hint: 'Вставьте ссылку на видео выше, и AI обработает его.',
        processing: 'Обработка...',
        downloading_video: 'Получение аудио URL...',
        parsing_video: 'Разбор информации о видео...',
        transcribing_audio: 'Транскрибация аудио...',
        optimizing_transcript: 'Оптимизация транскрипта...',
        generating_summary: 'Создание сводки...',
        detecting_subtitles: 'Поиск субтитров...',
        subtitle_found: 'Субтитры найдены, обрабатываю текст...',
        no_subtitle: 'Субтитры не найдены, получаю аудио URL для Groq...',
        mode_subtitle: 'Субтитры',
        mode_whisper: 'Groq URL',
        mode_groq: 'Groq URL',
        completed: 'Готово!',
        error_invalid_url: 'Введите корректную ссылку на видео',
        error_processing_failed: 'Ошибка обработки: ',
        error_no_download: 'Нет файла для скачивания',
        error_download_failed: 'Ошибка скачивания: ',
        fetching_models: 'Загрузка моделей...',
        models_loaded: (n) => `${n} моделей загружено`,
        models_error: 'Не удалось загрузить модели',
      },
      uk: {
        title: 'AI відео транскрибатор',
        subtitle: 'Автоматична транскрибація та AI-зведення для 30+ платформ',
        video_url_placeholder: 'Вставте посилання на YouTube, TikTok, Bilibili або інше відео...',
        start_transcription: 'Транскрибувати',
        ai_settings: 'Налаштування AI',
        groq_transcription: 'Транскрибація Groq',
        groq_api_key: 'Groq API Key',
        groq_api_key_placeholder: 'gsk_...',
        groq_model: 'Модель Groq Whisper',
        groq_language: 'Мова аудіо',
        groq_language_placeholder: 'auto',
        groq_prompt: 'Промпт Groq',
        groq_prompt_placeholder: 'Імена, тема, терміни...',
        include_timecodes: 'Додати таймкоди',
        copy_text: 'Копіювати текст',
        copied_text: 'Скопійовано',
        save_text: 'Зберегти',
        summary_provider: 'Провайдер зведення',
        model_base_url: 'Base URL API моделі',
        model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API Key',
        api_key_placeholder: 'sk-...',
        fetch_models: 'Завантажити',
        model_select: 'Модель',
        model_default: '-- використовувати модель сервера --',
        reasoning_effort: 'Міркування',
        reasoning_auto: 'Авто',
        reasoning_none: 'Немає',
        reasoning_minimal: 'Мінімальне',
        reasoning_low: 'Низьке',
        reasoning_medium: 'Середнє',
        reasoning_high: 'Високе',
        reasoning_xhigh: 'Дуже високе',
        summary_language: 'Мова зведення',
        summary_prompt_label: 'Промпт зведення',
        summary_prompt_placeholder: 'Необовʼязково: вкажіть, як створити зведення, наприклад "зосередься на діях і ризиках".',
        processing_progress: 'Обробка',
        preparing: 'Підготовка...',
        transcript_text: 'Транскрипт',
        intelligent_summary: 'AI-зведення',
        translation: 'Переклад',
        download_transcript: 'Транскрипт',
        download_translation: 'Переклад',
        download_summary: 'Зведення',
        download_summary_md: 'Зведення MD',
        download_summary_html: 'Зведення HTML',
        download_summary_txt: 'Зведення TXT',
        output_format: 'Формат виводу',
        format_markdown: 'Markdown',
        format_html: 'HTML',
        format_txt: 'TXT',
        format_both: 'Markdown + HTML',
        generate_summary: 'Створити зведення',
        summary_waiting: 'Транскрипт готовий. Створіть зведення, коли будете готові надіслати його провайдеру.',
        generating_summary_btn: 'Створення...',
        empty_hint: 'Вставте посилання на відео вище, і AI обробить його.',
        processing: 'Обробка...',
        downloading_video: 'Отримання аудіо URL...',
        parsing_video: 'Розбір інформації про відео...',
        transcribing_audio: 'Транскрибація аудіо...',
        optimizing_transcript: 'Оптимізація транскрипту...',
        generating_summary: 'Створення зведення...',
        detecting_subtitles: 'Пошук субтитрів...',
        subtitle_found: 'Субтитри знайдено, обробляю текст...',
        no_subtitle: 'Субтитри не знайдено, отримую аудіо URL для Groq...',
        mode_subtitle: 'Субтитри',
        mode_whisper: 'Groq URL',
        mode_groq: 'Groq URL',
        completed: 'Готово!',
        error_invalid_url: 'Введіть коректне посилання на відео',
        error_processing_failed: 'Помилка обробки: ',
        error_no_download: 'Немає файлу для завантаження',
        error_download_failed: 'Помилка завантаження: ',
        fetching_models: 'Завантаження моделей...',
        models_loaded: (n) => `${n} моделей завантажено`,
        models_error: 'Не вдалося завантажити моделі',
      },
      zh: {
        title: 'AI 视频转录工具',
        subtitle: '粘贴 YouTube、TikTok 或任何公开视频链接，获取转录文本和 AI 摘要。',
        video_url_placeholder: '粘贴视频链接...',
        start_transcription: '开始转录',
        ai_settings: 'AI 设置',
        groq_transcription: 'Groq 转录',
        groq_api_key: 'Groq API 密钥',
        groq_api_key_placeholder: 'gsk_...',
        groq_model: 'Groq Whisper 模型',
        groq_language: '输入语言',
        groq_language_placeholder: '自动检测',
        groq_prompt: 'Groq 提示词',
        groq_prompt_placeholder: '姓名、主题、拼写...',
        summary_provider: '摘要提供方',
        model_base_url: '模型 API 基础 URL',
        model_base_url_placeholder: 'https://openrouter.ai/api/v1',
        api_key: 'API 密钥',
        api_key_placeholder: 'sk-...',
        fetch_models: '获取',
        model_select: '模型',
        model_default: '— 使用服务器默认 —',
        reasoning_effort: '推理强度',
        reasoning_auto: '自动',
        reasoning_none: '无',
        reasoning_minimal: '极低',
        reasoning_low: '低',
        reasoning_medium: '中等',
        reasoning_high: '高',
        reasoning_xhigh: '极高',
        summary_language: '摘要语言',
        summary_prompt_label: '摘要提示词',
        summary_prompt_placeholder: '可选：告诉模型如何摘要，例如"关注行动项和风险"。',
        processing_progress: '处理进度',
        preparing: '准备中…',
        transcript_text: '转录文本',
        intelligent_summary: 'AI 摘要',
        translation: '翻译',
        download_transcript: '转录文本',
        download_translation: '翻译',
        download_summary: '摘要',
        download_summary_md: '摘要 MD',
        download_summary_html: '摘要 HTML',
        download_summary_txt: '摘要 TXT',
        output_format: '输出格式',
        format_markdown: 'Markdown',
        format_html: 'HTML',
        format_txt: 'TXT',
        format_both: 'Markdown + HTML',
        generate_summary: '生成摘要',
        summary_waiting: '转录已完成。准备好后即可生成摘要并发送给摘要提供方。',
        generating_summary_btn: '生成中...',
        empty_hint: '在上方粘贴视频链接，让 AI 为您处理。',
        processing: '处理中…',
        downloading_video: '获取音频链接…',
        parsing_video: '解析视频信息…',
        transcribing_audio: '转录音频中…',
        optimizing_transcript: '优化转录文本…',
        generating_summary: '生成摘要中…',
        detecting_subtitles: '检测字幕…',
        subtitle_found: '找到字幕！正在处理文本…',
        no_subtitle: '未找到字幕，获取 Groq 音频链接…',
        mode_subtitle: '字幕',
        mode_whisper: 'Groq URL',
        mode_groq: 'Groq URL',
        completed: '完成！',
        error_invalid_url: '请输入有效的视频链接',
        error_processing_failed: '处理失败：',
        error_no_download: '没有可下载的文件',
        error_download_failed: '下载失败：',
        fetching_models: '获取模型…',
        models_loaded: (n) => `已加载 ${n} 个模型`,
        models_error: '获取模型失败',
      }
    };

    Object.assign(this.i18n.en, {
      transcription_provider_section: 'Transcription Provider',
      transcription_provider: 'Transcription Provider',
      provider_groq: 'Groq',
      provider_local: 'Local',
      provider_local_api: 'Local API',
      try_subtitles_first: 'Try YouTube subtitles first',
      use_local_fallback: 'Use local model as fallback for Groq',
      local_transcription: 'Local Transcription',
      local_backend: 'Local Backend',
      local_backend_whisper: 'Whisper',
      local_backend_parakeet: 'Parakeet',
      local_model_preset: 'Local Model Preset',
      local_model_custom: 'Custom Local Model',
      local_model_custom_option: 'Custom model',
      local_model_custom_placeholder: 'openai/whisper-large-v3 or local path',
      local_language: 'Local Language Hint',
      local_language_placeholder: 'auto',
      local_runtime_notice: 'Runtime',
      runtime_cuda: 'CUDA',
      runtime_cpu: 'CPU',
      local_backend_ready: 'Local backend is available.',
      local_backend_unavailable: 'Local backend is unavailable.',
      local_backend_auto_install: 'Missing backend packages and the selected model will be installed automatically on first use.',
      local_capabilities_error: 'Failed to load local model capabilities.',
      parakeet_cpu_warning: 'Parakeet may be slow on CPU.',
      local_api_transcription: 'Local API Transcription',
      local_api_base_url: 'Local API Base URL',
      local_api_base_url_placeholder: 'http://127.0.0.1:11434/v1',
      local_api_key: 'Local API Key',
      local_api_key_placeholder: 'optional',
      local_api_model: 'Local API Model',
      local_api_model_placeholder: 'whisper-large-v3',
      local_api_language: 'Input Language',
      local_api_language_placeholder: 'auto',
      local_api_prompt: 'Transcription Prompt',
      local_api_prompt_placeholder: 'Names, topic, spelling...',
      local_api_notice: 'Use an OpenAI-compatible speech-to-text API endpoint.',
      source_mode_url: 'Video URL',
      source_mode_file: 'Local audio file',
      choose_audio_file: 'Choose audio file',
      no_audio_file_selected: 'No file selected',
      error_no_audio_file: 'Choose a local audio file',
      mode_local: 'Local',
      mode_local_api: 'Local API',
      mode_fallback: 'Local fallback',
      local_transcribing_audio: 'Transcribing with local model…',
      local_fallback_progress: 'Groq failed, running local fallback…',
      active_stage: 'Active stage',
      stage_elapsed_prefix: 'Elapsed',
      stage_checking_subtitles: 'Checking subtitles',
      stage_subtitle_skipped: 'Skipping subtitles',
      stage_reading_uploaded_audio: 'Reading uploaded audio',
      stage_downloading_audio: 'Downloading audio',
      stage_preparing_audio: 'Preparing audio',
      stage_installing_local_backend: 'Installing local backend',
      stage_loading_local_model: 'Loading local model',
      stage_transcribing_local_audio: 'Running local transcription',
      stage_merging_transcripts: 'Merging transcripts',
      stage_saving_transcript: 'Saving transcript',
      stage_resolving_groq_audio_url: 'Resolving Groq audio URL',
      stage_retrying_groq_audio_url: 'Refreshing Groq audio URL',
      stage_transcribing_groq_audio: 'Transcribing with Groq',
      stage_uploading_groq_audio: 'Uploading audio to Groq',
      stage_downloading_groq_fallback_audio: 'Downloading fallback audio',
      stage_uploading_groq_fallback_audio: 'Uploading fallback audio',
      stage_switching_to_local_fallback: 'Switching to local fallback',
      stage_sending_local_api_audio: 'Sending audio to local API',
      stage_completed: 'Completed',
      stage_error: 'Error',
      dual_local_transcription: 'Run Whisper + Parakeet together',
      dual_whisper_model: 'Whisper Model',
      dual_whisper_custom: 'Custom Whisper Model',
      dual_parakeet_model: 'Parakeet Model',
      dual_parakeet_custom: 'Custom Parakeet Model',
      merge_settings: 'Merge Settings',
      merge_use_ai: 'Use AI to merge transcripts',
      merge_base_url: 'Merge API Base URL',
      merge_api_key: 'Merge API Key',
      merge_model: 'Merge Model',
      merge_prompt: 'Merge Prompt',
      merge_prompt_placeholder: 'Optional: tell the model how to merge',
      merge_reasoning_effort: 'Merge Reasoning',
      mode_dual_local: 'Dual Local',
      stage_dual_transcribing: 'Running dual transcription',
      multi_source_section: 'Multi-Source Transcription',
      multi_source_enable: 'Enable multi-source transcription',
      transcription_sources_label: 'Transcription Sources',
      source_platform: 'Platform subtitles',
      source_groq: 'Groq Whisper',
      source_local_whisper: 'Local Whisper',
      source_local_parakeet: 'Local Parakeet',
      merge_mode_label: 'Merge Mode',
      merge_mode_system: 'System merge (deterministic)',
      merge_mode_raw: 'Raw bundle (no merge)',
      merge_mode_ai: 'AI merge',
      merge_primary_source: 'Primary Source',
      mode_multi_source: 'Multi-Source',
      stage_multi_source: 'Running multi-source transcription',
      source_status_title: 'Concurrent sources',
      source_status_pending: 'Queued',
      source_status_running: 'Running',
      source_status_completed: 'Done',
      source_status_failed: 'Failed',
    });

    Object.assign(this.i18n.ru, {
      transcription_provider_section: 'Провайдер транскрибации',
      transcription_provider: 'Провайдер транскрибации',
      provider_groq: 'Groq',
      provider_local: 'Локально',
      provider_local_api: 'Локальный API',
      try_subtitles_first: 'Сначала пробовать YouTube-субтитры',
      use_local_fallback: 'Использовать локальную модель как fallback для Groq',
      local_transcription: 'Локальная транскрибация',
      local_backend: 'Локальный движок',
      local_backend_whisper: 'Whisper',
      local_backend_parakeet: 'Parakeet',
      local_model_preset: 'Пресет локальной модели',
      local_model_custom: 'Своя локальная модель',
      local_model_custom_option: 'Своя модель',
      local_model_custom_placeholder: 'openai/whisper-large-v3 или локальный путь',
      local_language: 'Подсказка по языку',
      local_language_placeholder: 'auto',
      local_runtime_notice: 'Режим',
      runtime_cuda: 'CUDA',
      runtime_cpu: 'CPU',
      local_backend_ready: 'Локальный движок доступен.',
      local_backend_unavailable: 'Локальный движок недоступен.',
      local_backend_auto_install: 'Недостающие пакеты движка и выбранная модель будут установлены автоматически при первом запуске.',
      local_capabilities_error: 'Не удалось загрузить возможности локальных моделей.',
      parakeet_cpu_warning: 'Parakeet может работать медленно на CPU.',
      local_api_transcription: 'Транскрибация через локальный API',
      local_api_base_url: 'Base URL локального API',
      local_api_base_url_placeholder: 'http://127.0.0.1:11434/v1',
      local_api_key: 'Ключ локального API',
      local_api_key_placeholder: 'необязательно',
      local_api_model: 'Модель локального API',
      local_api_model_placeholder: 'whisper-large-v3',
      local_api_language: 'Язык аудио',
      local_api_language_placeholder: 'auto',
      local_api_prompt: 'Промпт транскрибации',
      local_api_prompt_placeholder: 'Имена, тема, термины...',
      local_api_notice: 'Используйте OpenAI-совместимый speech-to-text API endpoint.',
      source_mode_url: 'Ссылка на видео',
      source_mode_file: 'Локальный аудиофайл',
      choose_audio_file: 'Выбрать аудиофайл',
      no_audio_file_selected: 'Файл не выбран',
      error_no_audio_file: 'Выберите локальный аудиофайл',
      mode_local: 'Локально',
      mode_local_api: 'Локальный API',
      mode_fallback: 'Локальный fallback',
      local_transcribing_audio: 'Транскрибация локальной моделью…',
      local_fallback_progress: 'Groq недоступен, запускаю локальный fallback…',
      active_stage: 'Текущий этап',
      stage_elapsed_prefix: 'Время',
      stage_checking_subtitles: 'Проверка субтитров',
      stage_subtitle_skipped: 'Пропуск субтитров',
      stage_reading_uploaded_audio: 'Чтение загруженного аудио',
      stage_downloading_audio: 'Загрузка аудио',
      stage_preparing_audio: 'Подготовка аудио',
      stage_installing_local_backend: 'Установка локального движка',
      stage_loading_local_model: 'Загрузка локальной модели',
      stage_transcribing_local_audio: 'Локальная транскрибация',
      stage_merging_transcripts: 'Слияние транскриптов',
      stage_saving_transcript: 'Сохранение транскрипта',
      stage_resolving_groq_audio_url: 'Получение аудио URL для Groq',
      stage_retrying_groq_audio_url: 'Обновление аудио URL для Groq',
      stage_transcribing_groq_audio: 'Транскрибация через Groq',
      stage_uploading_groq_audio: 'Загрузка аудио в Groq',
      stage_downloading_groq_fallback_audio: 'Загрузка аудио для fallback',
      stage_uploading_groq_fallback_audio: 'Загрузка файла в Groq',
      stage_switching_to_local_fallback: 'Переключение на локальный fallback',
      stage_sending_local_api_audio: 'Отправка аудио в локальный API',
      stage_completed: 'Завершено',
      stage_error: 'Ошибка',
      dual_local_transcription: 'Запустить Whisper + Parakeet вместе',
      dual_whisper_model: 'Модель Whisper',
      dual_whisper_custom: 'Своя модель Whisper',
      dual_parakeet_model: 'Модель Parakeet',
      dual_parakeet_custom: 'Своя модель Parakeet',
      merge_settings: 'Настройки слияния',
      merge_use_ai: 'Использовать AI для слияния транскриптов',
      merge_base_url: 'Base URL API слияния',
      merge_api_key: 'Ключ API слияния',
      merge_model: 'Модель слияния',
      merge_prompt: 'Промпт слияния',
      merge_prompt_placeholder: 'Необязательно: укажите, как слить',
      merge_reasoning_effort: 'Рассуждение слияния',
      mode_dual_local: 'Двойное локальное',
      stage_dual_transcribing: 'Двойная транскрибация',
      multi_source_section: 'Мультиисточниковая транскрибация',
      multi_source_enable: 'Включить мультиисточниковую транскрибацию',
      transcription_sources_label: 'Источники транскрибации',
      source_platform: 'Субтитры платформы',
      source_groq: 'Groq Whisper',
      source_local_whisper: 'Локальный Whisper',
      source_local_parakeet: 'Локальный Parakeet',
      merge_mode_label: 'Режим слияния',
      merge_mode_system: 'Системное слияние (детерминированное)',
      merge_mode_raw: 'Исходный набор (без слияния)',
      merge_mode_ai: 'AI слияние',
      merge_primary_source: 'Основной источник',
      mode_multi_source: 'Мультиисточник',
      stage_multi_source: 'Запуск мультиисточниковой транскрибации',
      source_status_title: 'Параллельные источники',
      source_status_pending: 'В очереди',
      source_status_running: 'В работе',
      source_status_completed: 'Готово',
      source_status_failed: 'Ошибка',
    });

    Object.assign(this.i18n.uk, {
      transcription_provider_section: 'Провайдер транскрибування',
      transcription_provider: 'Провайдер транскрибування',
      provider_groq: 'Groq',
      provider_local: 'Локально',
      provider_local_api: 'Локальний API',
      try_subtitles_first: 'Спочатку пробувати YouTube-субтитри',
      use_local_fallback: 'Використовувати локальну модель як fallback для Groq',
      local_transcription: 'Локальне транскрибування',
      local_backend: 'Локальний рушій',
      local_backend_whisper: 'Whisper',
      local_backend_parakeet: 'Parakeet',
      local_model_preset: 'Пресет локальної моделі',
      local_model_custom: 'Власна локальна модель',
      local_model_custom_option: 'Власна модель',
      local_model_custom_placeholder: 'openai/whisper-large-v3 або локальний шлях',
      local_language: 'Підказка щодо мови',
      local_language_placeholder: 'auto',
      local_runtime_notice: 'Режим',
      runtime_cuda: 'CUDA',
      runtime_cpu: 'CPU',
      local_backend_ready: 'Локальний рушій доступний.',
      local_backend_unavailable: 'Локальний рушій недоступний.',
      local_backend_auto_install: 'Відсутні пакети рушія та вибрана модель будуть встановлені автоматично під час першого запуску.',
      local_capabilities_error: 'Не вдалося завантажити можливості локальних моделей.',
      parakeet_cpu_warning: 'Parakeet може працювати повільно на CPU.',
      local_api_transcription: 'Транскрибування через локальний API',
      local_api_base_url: 'Base URL локального API',
      local_api_base_url_placeholder: 'http://127.0.0.1:11434/v1',
      local_api_key: 'Ключ локального API',
      local_api_key_placeholder: 'необовʼязково',
      local_api_model: 'Модель локального API',
      local_api_model_placeholder: 'whisper-large-v3',
      local_api_language: 'Мова аудіо',
      local_api_language_placeholder: 'auto',
      local_api_prompt: 'Промпт транскрибування',
      local_api_prompt_placeholder: 'Імена, тема, терміни...',
      local_api_notice: 'Використовуйте OpenAI-сумісний speech-to-text API endpoint.',
      source_mode_url: 'Посилання на відео',
      source_mode_file: 'Локальний аудіофайл',
      choose_audio_file: 'Обрати аудіофайл',
      no_audio_file_selected: 'Файл не вибрано',
      error_no_audio_file: 'Оберіть локальний аудіофайл',
      mode_local: 'Локально',
      mode_local_api: 'Локальний API',
      mode_fallback: 'Локальний fallback',
      local_transcribing_audio: 'Транскрибування локальною моделлю…',
      local_fallback_progress: 'Groq недоступний, запускаю локальний fallback…',
      active_stage: 'Поточний етап',
      stage_elapsed_prefix: 'Час',
      stage_checking_subtitles: 'Перевірка субтитрів',
      stage_subtitle_skipped: 'Пропуск субтитрів',
      stage_reading_uploaded_audio: 'Читання завантаженого аудіо',
      stage_downloading_audio: 'Завантаження аудіо',
      stage_preparing_audio: 'Підготовка аудіо',
      stage_installing_local_backend: 'Встановлення локального рушія',
      stage_loading_local_model: 'Завантаження локальної моделі',
      stage_transcribing_local_audio: 'Локальне транскрибування',
      stage_merging_transcripts: 'Злиття транскриптів',
      stage_saving_transcript: 'Збереження транскрипту',
      stage_resolving_groq_audio_url: 'Отримання аудіо URL для Groq',
      stage_retrying_groq_audio_url: 'Оновлення аудіо URL для Groq',
      stage_transcribing_groq_audio: 'Транскрибування через Groq',
      stage_uploading_groq_audio: 'Завантаження аудіо в Groq',
      stage_downloading_groq_fallback_audio: 'Завантаження аудіо для fallback',
      stage_uploading_groq_fallback_audio: 'Завантаження файла в Groq',
      stage_switching_to_local_fallback: 'Перехід на локальний fallback',
      stage_sending_local_api_audio: 'Надсилання аудіо в локальний API',
      stage_completed: 'Завершено',
      stage_error: 'Помилка',
      dual_local_transcription: 'Запустити Whisper + Parakeet разом',
      dual_whisper_model: 'Модель Whisper',
      dual_whisper_custom: 'Власна модель Whisper',
      dual_parakeet_model: 'Модель Parakeet',
      dual_parakeet_custom: 'Власна модель Parakeet',
      merge_settings: 'Налаштування злиття',
      merge_use_ai: 'Використовувати AI для злиття транскриптів',
      merge_base_url: 'Base URL API злиття',
      merge_api_key: 'Ключ API злиття',
      merge_model: 'Модель злиття',
      merge_prompt: 'Промпт злиття',
      merge_prompt_placeholder: 'Необовʼязково: вкажіть, як злити',
      merge_reasoning_effort: 'Міркування злиття',
      mode_dual_local: 'Подвійне локальне',
      stage_dual_transcribing: 'Подвійне транскрибування',
      multi_source_section: 'Мультіджерельне транскрибування',
      multi_source_enable: 'Увімкнути мультіджерельне транскрибування',
      transcription_sources_label: 'Джерела транскрибування',
      source_platform: 'Субтитри платформи',
      source_groq: 'Groq Whisper',
      source_local_whisper: 'Локальний Whisper',
      source_local_parakeet: 'Локальний Parakeet',
      merge_mode_label: 'Режим злиття',
      merge_mode_system: 'Системне злиття (детерміноване)',
      merge_mode_raw: 'Сирий набір (без злиття)',
      merge_mode_ai: 'AI злиття',
      merge_primary_source: 'Основне джерело',
      mode_multi_source: 'Мультіджерельний',
      stage_multi_source: 'Запуск мультіджерельного транскрибування',
      source_status_title: 'Паралельні джерела',
      source_status_pending: 'У черзі',
      source_status_running: 'В роботі',
      source_status_completed: 'Готово',
      source_status_failed: 'Помилка',
    });

    Object.assign(this.i18n.zh, {
      transcription_provider_section: '转录提供方',
      transcription_provider: '转录提供方',
      provider_groq: 'Groq',
      provider_local: '本地',
      provider_local_api: '本地 API',
      try_subtitles_first: '优先尝试 YouTube 字幕',
      use_local_fallback: '使用本地模型作为 Groq 的后备方案',
      local_transcription: '本地转录',
      local_backend: '本地引擎',
      local_backend_whisper: 'Whisper',
      local_backend_parakeet: 'Parakeet',
      local_model_preset: '本地模型预设',
      local_model_custom: '自定义本地模型',
      local_model_custom_option: '自定义模型',
      local_model_custom_placeholder: 'openai/whisper-large-v3 或本地路径',
      local_language: '语言提示',
      local_language_placeholder: '自动检测',
      local_runtime_notice: '运行时',
      runtime_cuda: 'CUDA',
      runtime_cpu: 'CPU',
      local_backend_ready: '本地引擎可用。',
      local_backend_unavailable: '本地引擎不可用。',
      local_backend_auto_install: '缺少的引擎包和所选模型将在首次使用时自动安装。',
      local_capabilities_error: '加载本地模型能力失败。',
      parakeet_cpu_warning: 'Parakeet 在 CPU 上可能较慢。',
      local_api_transcription: '本地 API 转录',
      local_api_base_url: '本地 API 基础 URL',
      local_api_base_url_placeholder: 'http://127.0.0.1:11434/v1',
      local_api_key: '本地 API 密钥',
      local_api_key_placeholder: '可选',
      local_api_model: '本地 API 模型',
      local_api_model_placeholder: 'whisper-large-v3',
      local_api_language: '输入语言',
      local_api_language_placeholder: '自动检测',
      local_api_prompt: '转录提示词',
      local_api_prompt_placeholder: '姓名、主题、拼写...',
      local_api_notice: '使用兼容 OpenAI 的语音转文字 API 端点。',
      source_mode_url: '视频链接',
      source_mode_file: '本地音频文件',
      choose_audio_file: '选择音频文件',
      no_audio_file_selected: '未选择文件',
      error_no_audio_file: '请选择本地音频文件',
      mode_local: '本地',
      mode_local_api: '本地 API',
      mode_fallback: '本地后备',
      local_transcribing_audio: '本地模型转录中…',
      local_fallback_progress: 'Groq 失败，正在启动本地后备方案…',
      active_stage: '当前阶段',
      stage_elapsed_prefix: '耗时',
      stage_checking_subtitles: '检查字幕',
      stage_subtitle_skipped: '跳过字幕',
      stage_reading_uploaded_audio: '读取上传音频',
      stage_downloading_audio: '下载音频',
      stage_preparing_audio: '准备音频',
      stage_installing_local_backend: '安装本地引擎',
      stage_loading_local_model: '加载本地模型',
      stage_transcribing_local_audio: '本地转录中',
      stage_merging_transcripts: '合并转录文本',
      stage_saving_transcript: '保存转录文本',
      stage_resolving_groq_audio_url: '获取 Groq 音频链接',
      stage_retrying_groq_audio_url: '刷新 Groq 音频链接',
      stage_transcribing_groq_audio: 'Groq 转录中',
      stage_uploading_groq_audio: '上传音频至 Groq',
      stage_downloading_groq_fallback_audio: '下载后备音频',
      stage_uploading_groq_fallback_audio: '上传后备音频至 Groq',
      stage_switching_to_local_fallback: '切换到本地后备方案',
      stage_sending_local_api_audio: '发送音频至本地 API',
      stage_completed: '已完成',
      stage_error: '错误',
      dual_local_transcription: '同时运行 Whisper + Parakeet',
      dual_whisper_model: 'Whisper 模型',
      dual_whisper_custom: '自定义 Whisper 模型',
      dual_parakeet_model: 'Parakeet 模型',
      dual_parakeet_custom: '自定义 Parakeet 模型',
      merge_settings: '合并设置',
      merge_use_ai: '使用 AI 合并转录文本',
      merge_base_url: '合并 API 基础 URL',
      merge_api_key: '合并 API 密钥',
      merge_model: '合并模型',
      merge_prompt: '合并提示词',
      merge_prompt_placeholder: '可选：告诉模型如何合并',
      merge_reasoning_effort: '合并推理',
      mode_dual_local: '双本地',
      stage_dual_transcribing: '双重转录中',
      multi_source_section: '多源转录',
      multi_source_enable: '启用多源转录',
      transcription_sources_label: '转录来源',
      source_platform: '平台字幕',
      source_groq: 'Groq Whisper',
      source_local_whisper: '本地 Whisper',
      source_local_parakeet: '本地 Parakeet',
      merge_mode_label: '合并模式',
      merge_mode_system: '系统合并（确定性）',
      merge_mode_raw: '原始包（不合并）',
      merge_mode_ai: 'AI 合并',
      merge_primary_source: '主要来源',
      mode_multi_source: '多源',
      stage_multi_source: '正在运行多源转录',
      source_status_title: '并发来源',
      source_status_pending: '排队中',
      source_status_running: '运行中',
      source_status_completed: '完成',
      source_status_failed: '失败',
    });

    this._initElements();
    this._bindEvents();
    this._loadSettings();
    this._switchLang(this._savedUiLang || 'en');
    this._updateReasoningAvailability();
    this._fetchLocalCapabilities();
    this._syncProviderSettings();
    this._loadServerSettings();
  }

  /* -- Elements -------------------------------------------------- */
  _initElements() {
    this.form = document.getElementById('videoForm');
    this.sourceModeUrlBtn = document.getElementById('sourceModeUrl');
    this.sourceModeFileBtn = document.getElementById('sourceModeFile');
    this.urlInputWrap = document.getElementById('urlInputWrap');
    this.audioFileWrap = document.getElementById('audioFileWrap');
    this.audioFileInput = document.getElementById('audioFileInput');
    this.audioFileName = document.getElementById('audioFileName');
    this.videoUrlInput = document.getElementById('videoUrl');
    this.submitBtn = document.getElementById('submitBtn');
    this.summaryLangSel = document.getElementById('summaryLanguage');
    this.langSwitcher = document.getElementById('langSwitcher');
    this.langToggle = document.getElementById('langToggle');
    this.langText = document.getElementById('langText');
    this.langMenu = document.getElementById('langMenu');
    this.langOptions = Array.from(document.querySelectorAll('.lang-option'));
    this.errorBanner = document.getElementById('errorBanner');
    this.errorMsg = document.getElementById('errorMsg');
    this.errorCloseBtn = document.getElementById('errorCloseBtn');
    this.emptyState = document.getElementById('emptyState');
    this.progressPanel = document.getElementById('progressPanel');
    this.modeBadge = document.getElementById('modeBadge');
    this.progressStatus = document.getElementById('progressStatus');
    this.progressFill = document.getElementById('progressFill');
    this.progressMessage = document.getElementById('progressMessage');
    this.stageCurrent = document.getElementById('stageCurrent');
    this.stageElapsed = document.getElementById('stageElapsed');
    this.stageTimeline = document.getElementById('stageTimeline');
    this.sourceStatusPanel = document.getElementById('sourceStatusPanel');
    this.resultsPanel = document.getElementById('resultsPanel');
    this.scriptContent = document.getElementById('scriptContent');
    this.copyTranscriptTop = document.getElementById('copyTranscriptTop');
    this.copyTranscriptBottom = document.getElementById('copyTranscriptBottom');
    this.saveTranscriptTop = document.getElementById('saveTranscriptTop');
    this.saveTranscriptBottom = document.getElementById('saveTranscriptBottom');
    this.saveTranscriptFormatTop = document.getElementById('saveTranscriptFormatTop');
    this.saveTranscriptFormatBottom = document.getElementById('saveTranscriptFormatBottom');
    this.summaryContent = document.getElementById('summaryContent');
    this.summaryPrompt = document.getElementById('summaryPrompt');
    this.summaryActionsTop = document.getElementById('summaryActionsTop');
    this.summaryActionsBottom = document.getElementById('summaryActionsBottom');
    this.copySummaryTop = document.getElementById('copySummaryTop');
    this.copySummaryBottom = document.getElementById('copySummaryBottom');
    this.saveSummaryTop = document.getElementById('saveSummaryTop');
    this.saveSummaryBottom = document.getElementById('saveSummaryBottom');
    this.saveSummaryFormatTop = document.getElementById('saveSummaryFormatTop');
    this.saveSummaryFormatBottom = document.getElementById('saveSummaryFormatBottom');
    this.translationContent = document.getElementById('translationContent');
    this.dlTranslation = document.getElementById('downloadTranslation');
    this.dlSummary = document.getElementById('downloadSummary');
    this.dlSummaryHtml = document.getElementById('downloadSummaryHtml');
    this.dlSummaryTxt = document.getElementById('downloadSummaryTxt');
    this.generateSummaryBtn = document.getElementById('generateSummary');
    this.summaryFormatSel = document.getElementById('summaryFormat');
    this.summaryPromptInput = document.getElementById('summaryPromptInput');
    this.translationTabBtn = document.getElementById('translationTabBtn');
    this.tabBtns = document.querySelectorAll('.tab-btn');
    this.tabPanes = document.querySelectorAll('.tab-pane');
    // settings
    this.settingsToggle = document.getElementById('settingsToggle');
    this.settingsBody = document.getElementById('settingsBody');
    this.modelBaseUrl = document.getElementById('modelBaseUrl');
    this.apiKeyInput = document.getElementById('apiKeyInput');
    this.groqApiKeyInput = document.getElementById('groqApiKeyInput');
    this.groqModelSelect = document.getElementById('groqModelSelect');
    this.groqLanguageInput = document.getElementById('groqLanguageInput');
    this.groqPromptInput = document.getElementById('groqPromptInput');
    this.transcriptionProviderSelect = document.getElementById('transcriptionProviderSelect');
    this.trySubtitlesFirstInput = document.getElementById('trySubtitlesFirstInput');
    this.trySubtitlesFirstRow = this.trySubtitlesFirstInput?.closest('.check-row');
    this.useLocalFallbackInput = document.getElementById('useLocalFallbackInput');
    this.useLocalFallbackRow = document.getElementById('useLocalFallbackRow');
    this.localBackendSelect = document.getElementById('localBackendSelect');
    this.localModelPresetSelect = document.getElementById('localModelPresetSelect');
    this.localModelCustomRow = document.getElementById('localModelCustomRow');
    this.localModelIdInput = document.getElementById('localModelIdInput');
    this.localLanguageInput = document.getElementById('localLanguageInput');
    this.localCapabilitiesNotice = document.getElementById('localCapabilitiesNotice');
    this.localCapabilitiesDetail = document.getElementById('localCapabilitiesDetail');
    this.localApiBaseUrlInput = document.getElementById('localApiBaseUrlInput');
    this.localApiKeyInput = document.getElementById('localApiKeyInput');
    this.localApiModelInput = document.getElementById('localApiModelInput');
    this.localApiLanguageInput = document.getElementById('localApiLanguageInput');
    this.localApiPromptInput = document.getElementById('localApiPromptInput');
    this.localApiSettings = Array.from(document.querySelectorAll('.local-api-setting'));
    this.groqSettings = Array.from(document.querySelectorAll('.groq-setting'));
    this.localSettings = Array.from(document.querySelectorAll('.local-setting'));
    this.includeTimecodesInput = document.getElementById('includeTimecodesInput');
    this.fetchModelsBtn = document.getElementById('fetchModelsBtn');
    this.fetchStatus = document.getElementById('fetchStatus');
    this.modelSelect = document.getElementById('modelSelect');
    this.reasoningEffortSelect = document.getElementById('reasoningEffortSelect');
    this.fetchIcon = document.getElementById('fetchIcon');
    this.localCapabilities = null;
    this.dualLocalInput = document.getElementById('dualLocalInput');
    this.dualLocalRow = document.getElementById('dualLocalRow');
    this.dualWhisperModelPresetSelect = document.getElementById('dualWhisperModelPresetSelect');
    this.dualWhisperCustomRow = document.getElementById('dualWhisperCustomRow');
    this.dualWhisperModelIdInput = document.getElementById('dualWhisperModelIdInput');
    this.dualParakeetModelPresetSelect = document.getElementById('dualParakeetModelPresetSelect');
    this.dualParakeetCustomRow = document.getElementById('dualParakeetCustomRow');
    this.dualParakeetModelIdInput = document.getElementById('dualParakeetModelIdInput');
    this.mergeUseAiInput = document.getElementById('mergeUseAiInput');
    this.mergeBaseUrlInput = document.getElementById('mergeBaseUrlInput');
    this.mergeApiKeyInput = document.getElementById('mergeApiKeyInput');
    this.mergeModelInput = document.getElementById('mergeModelInput');
    this.mergePromptInput = document.getElementById('mergePromptInput');
    this.mergeReasoningEffortSelect = document.getElementById('mergeReasoningEffortSelect');
    this.dualLocalSettings = Array.from(document.querySelectorAll('.dual-local-setting'));
    // Multi-source elements
    this.multiSourceEnabledInput = document.getElementById('multiSourceEnabledInput');
    this.sourceCheckboxes = Array.from(document.querySelectorAll('.source-checkbox'));
    this.multiSourceProviderPicker = document.querySelector('.multi-source-provider-picker');
    this.mergeModeSelect = document.getElementById('mergeModeSelect');
    this.mergePrimarySourceSelect = document.getElementById('mergePrimarySourceSelect');
    this.mergePrimarySourceRow = document.getElementById('mergePrimarySourceRow');
    this.msMergeBaseUrlInput = document.getElementById('msMergeBaseUrlInput');
    this.msMergeApiKeyInput = document.getElementById('msMergeApiKeyInput');
    this.msMergeModelInput = document.getElementById('msMergeModelInput');
    this.msMergeFetchModelsBtn = document.getElementById('msMergeFetchModelsBtn');
    this.msMergeFetchIcon = document.getElementById('msMergeFetchIcon');
    this.msMergeFetchStatus = document.getElementById('msMergeFetchStatus');
    this.multiSourceSections = Array.from(document.querySelectorAll('.multi-source-section:not(.ms-source-picker)'));
    this.msMergeAiSettings = Array.from(document.querySelectorAll('.multi-source-merge-ai'));
  }

  /* -- Events ---------------------------------------------------- */
  _bindEvents() {
    this.form.addEventListener('submit', (e) => { e.preventDefault(); this._startTranscription(); });
    this.errorCloseBtn?.addEventListener('click', () => this._hideError());
    this.sourceModeUrlBtn?.addEventListener('click', () => this._setInputSourceMode('url'));
    this.sourceModeFileBtn?.addEventListener('click', () => this._setInputSourceMode('file'));
    this.audioFileInput?.addEventListener('change', () => {
      this._renderSelectedAudioFile();
      this._saveSettings();
    });

    this.langToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      this._toggleLangMenu();
    });
    this.langOptions.forEach(option => {
      option.addEventListener('click', (e) => {
        e.stopPropagation();
        this._switchLang(option.dataset.lang);
        this._saveSettings();
        this._closeLangMenu();
        this.langToggle.focus();
      });
    });
    document.addEventListener('click', (e) => {
      if (!this.langSwitcher.contains(e.target)) this._closeLangMenu();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this._closeLangMenu();
    });

    // Settings toggle
    this.settingsToggle.addEventListener('click', () => {
      const open = this.settingsBody.classList.toggle('open');
      this.settingsToggle.classList.toggle('open', open);
    });

    // Fetch models
    this.fetchModelsBtn.addEventListener('click', () => this._fetchModels());
    this.modelSelect.addEventListener('change', () => this._updateReasoningAvailability());
    this.msMergeFetchModelsBtn?.addEventListener('click', () => this._fetchMergeModels());
    this.transcriptionProviderSelect.addEventListener('change', () => {
      this._syncProviderSettings();
      this._saveSettings();
    });
    this.useLocalFallbackInput.addEventListener('change', () => {
      this._syncProviderSettings();
      this._saveSettings();
    });
    this.localBackendSelect.addEventListener('change', () => {
      this._populateLocalModelPresets();
      this._syncProviderSettings();
      this._saveSettings();
    });
    this.localModelPresetSelect.addEventListener('change', () => {
      this._syncProviderSettings();
      this._saveSettings();
    });
    this.dualLocalInput.addEventListener('change', () => {
      this._syncDualSettings();
      this._saveSettings();
    });
    this.multiSourceEnabledInput?.addEventListener('change', () => {
      this._syncMultiSourceSettings();
      this._saveSettings();
    });
    this.sourceCheckboxes.forEach(cb => {
      cb.addEventListener('change', () => {
        this._syncMultiSourceSettings();
        this._saveSettings();
      });
    });
    this.mergeModeSelect?.addEventListener('change', () => {
      this._syncMultiSourceSettings();
      this._saveSettings();
    });
    this.mergePrimarySourceSelect?.addEventListener('change', () => this._saveSettings());
    this.dualWhisperModelPresetSelect.addEventListener('change', () => {
      this._syncDualSettings();
      this._saveSettings();
    });
    this.dualParakeetModelPresetSelect.addEventListener('change', () => {
      this._syncDualSettings();
      this._saveSettings();
    });

    // Auto-fetch when both fields filled (debounced)
    const debouncedFetch = this._debounce(() => {
      if (this.modelBaseUrl.value.trim() && this.apiKeyInput.value.trim()) this._fetchModels();
    }, 900);
    this.modelBaseUrl.addEventListener('input', debouncedFetch);
    this.apiKeyInput.addEventListener('input', debouncedFetch);
    const debouncedMergeFetch = this._debounce(() => {
      if (this.msMergeBaseUrlInput?.value.trim() && this.msMergeApiKeyInput?.value.trim()) {
        this._fetchMergeModels(true);
      }
    }, 900);
    this.msMergeBaseUrlInput?.addEventListener('input', debouncedMergeFetch);
    this.msMergeApiKeyInput?.addEventListener('input', debouncedMergeFetch);

    // Persist settings
    [
      this.modelBaseUrl,
      this.apiKeyInput,
      this.modelSelect,
      this.reasoningEffortSelect,
      this.summaryLangSel,
      this.groqApiKeyInput,
      this.groqModelSelect,
      this.groqLanguageInput,
      this.groqPromptInput,
      this.trySubtitlesFirstInput,
      this.localModelIdInput,
      this.localLanguageInput,
      this.localApiBaseUrlInput,
      this.localApiKeyInput,
      this.localApiModelInput,
      this.localApiLanguageInput,
      this.localApiPromptInput,
      this.includeTimecodesInput,
      this.summaryFormatSel,
      this.summaryPromptInput,
      this.dualLocalInput,
      this.dualWhisperModelPresetSelect,
      this.dualWhisperModelIdInput,
      this.dualParakeetModelPresetSelect,
      this.dualParakeetModelIdInput,
      this.mergeUseAiInput,
      this.mergeBaseUrlInput,
      this.mergeApiKeyInput,
      this.mergeModelInput,
      this.mergePromptInput,
      this.mergeReasoningEffortSelect,
      this.mergeModeSelect,
      this.mergePrimarySourceSelect,
      this.msMergeBaseUrlInput,
      this.msMergeApiKeyInput,
      this.msMergeModelInput,
    ].forEach(el => {
      el.addEventListener('change', () => this._saveSettings());
    });

    // Tabs
    this.tabBtns.forEach(btn => {
      btn.addEventListener('click', () => this._switchTab(btn.dataset.tab));
    });

    // Downloads
    this.dlTranslation.addEventListener('click', () => this._downloadFile('translation'));
    this.dlSummary.addEventListener('click', () => this._downloadFile('summary_md'));
    this.dlSummaryHtml.addEventListener('click', () => this._downloadFile('summary_html'));
    this.dlSummaryTxt.addEventListener('click', () => this._downloadFile('summary_txt'));
    this.generateSummaryBtn.addEventListener('click', () => this._generateSummary());
    this.copyTranscriptTop.addEventListener('click', () => this._copyTranscriptText(this.copyTranscriptTop));
    this.copyTranscriptBottom.addEventListener('click', () => this._copyTranscriptText(this.copyTranscriptBottom));
    this.saveTranscriptTop.addEventListener('click', () => this._saveTranscript(this.saveTranscriptFormatTop.value));
    this.saveTranscriptBottom.addEventListener('click', () => this._saveTranscript(this.saveTranscriptFormatBottom.value));
    this.copySummaryTop.addEventListener('click', () => this._copySummaryText(this.copySummaryTop));
    this.copySummaryBottom.addEventListener('click', () => this._copySummaryText(this.copySummaryBottom));
    this.saveSummaryTop.addEventListener('click', () => this._saveSummary(this.saveSummaryFormatTop.value));
    this.saveSummaryBottom.addEventListener('click', () => this._saveSummary(this.saveSummaryFormatBottom.value));
    this.saveTranscriptFormatTop.addEventListener('change', () => {
      this.saveTranscriptFormatBottom.value = this.saveTranscriptFormatTop.value;
      this._saveSettings();
    });
    this.saveTranscriptFormatBottom.addEventListener('change', () => {
      this.saveTranscriptFormatTop.value = this.saveTranscriptFormatBottom.value;
      this._saveSettings();
    });
    this.saveSummaryFormatTop.addEventListener('change', () => {
      this.saveSummaryFormatBottom.value = this.saveSummaryFormatTop.value;
      this._saveSettings();
    });
    this.saveSummaryFormatBottom.addEventListener('change', () => {
      this.saveSummaryFormatTop.value = this.saveSummaryFormatBottom.value;
      this._saveSettings();
    });
  }

  /* -- i18n ------------------------------------------------------ */
  t(key) {
    const active = this.i18n[this.currentLang] || this.i18n.en;
    return active[key] || this.i18n.en[key] || key;
  }

  _switchLang(lang) {
    if (!this.uiLanguages.includes(lang)) lang = 'en';
    this.currentLang = lang;
    this.langText.textContent = this.langLabels[lang] || this.langLabels.en;
    document.documentElement.lang = this.htmlLangs[lang] || 'en';
    document.title = this.t('title');

    document.querySelectorAll('[data-i18n]').forEach(el => {
      const v = this.t(el.dataset.i18n);
      if (typeof v === 'string') {
        el.textContent = v;
      }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const v = this.t(el.dataset.i18nPlaceholder);
      if (typeof v === 'string') el.placeholder = v;
    });
    this._renderSelectedAudioFile();
    this._renderSourceMode();
    this._renderLocalCapabilities();
    this._syncLangMenu();
  }

  _setInputSourceMode(mode) {
    this.inputSourceMode = mode === 'file' ? 'file' : 'url';
    this._renderSourceMode();
    this._syncProviderSettings();
    this._saveSettings();
  }

  _renderSourceMode() {
    const fileMode = this.inputSourceMode === 'file';
    this.sourceModeUrlBtn?.classList.toggle('active', !fileMode);
    this.sourceModeFileBtn?.classList.toggle('active', fileMode);
    this.urlInputWrap?.classList.toggle('setting-hidden', fileMode);
    this.audioFileWrap?.classList.toggle('setting-hidden', !fileMode);
    if (this.videoUrlInput) this.videoUrlInput.disabled = fileMode;
    if (this.audioFileInput) this.audioFileInput.disabled = !fileMode;
  }

  _renderSelectedAudioFile() {
    if (!this.audioFileName) return;
    const file = this.audioFileInput?.files?.[0];
    this.audioFileName.textContent = file?.name || this.t('no_audio_file_selected');
  }

  _toggleLangMenu() {
    if (this.langMenu.hidden) this._openLangMenu();
    else this._closeLangMenu();
  }

  _openLangMenu() {
    this._syncLangMenu();
    this.langMenu.hidden = false;
    this.langToggle.setAttribute('aria-expanded', 'true');
  }

  _closeLangMenu() {
    this.langMenu.hidden = true;
    this.langToggle.setAttribute('aria-expanded', 'false');
  }

  _syncLangMenu() {
    this.langOptions.forEach(option => {
      const active = option.dataset.lang === this.currentLang;
      option.classList.toggle('active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }

  /* -- Settings persistence -------------------------------------- */
  _saveSettings() {
    const s = {
      uiLang: this.currentLang,
      inputSourceMode: this.inputSourceMode,
      baseUrl: this.modelBaseUrl.value,
      apiKey: this.apiKeyInput.value,
      model: this.modelSelect.value,
      reasoningEffort: this.reasoningEffortSelect.value,
      summaryLang: this.summaryLangSel.value,
      groqApiKey: this.groqApiKeyInput.value,
      groqModel: this.groqModelSelect.value,
      groqLanguage: this.groqLanguageInput.value,
      groqPrompt: this.groqPromptInput.value,
      transcriptionProvider: this.transcriptionProviderSelect.value,
      trySubtitlesFirst: this.trySubtitlesFirstInput.checked,
      useLocalFallback: this.useLocalFallbackInput.checked,
      localBackend: this.localBackendSelect.value,
      localModelPreset: this.localModelPresetSelect.value,
      localModelId: this.localModelIdInput.value,
      localLanguage: this.localLanguageInput.value,
      localApiBaseUrl: this.localApiBaseUrlInput.value,
      localApiKey: this.localApiKeyInput.value,
      localApiModel: this.localApiModelInput.value,
      localApiLanguage: this.localApiLanguageInput.value,
      localApiPrompt: this.localApiPromptInput.value,
      includeTimecodes: this.includeTimecodesInput.checked,
      summaryFormat: this.summaryFormatSel.value,
      summaryPrompt: this.summaryPromptInput.value,
      transcriptSaveFormat: this.saveTranscriptFormatTop.value,
      summarySaveFormat: this.saveSummaryFormatTop.value,
      dualLocal: this.dualLocalInput.checked,
      dualWhisperModelPreset: this.dualWhisperModelPresetSelect?.value || 'base',
      dualWhisperModelId: this.dualWhisperModelIdInput?.value || '',
      dualParakeetModelPreset: this.dualParakeetModelPresetSelect?.value || '',
      dualParakeetModelId: this.dualParakeetModelIdInput?.value || '',
      mergeUseAi: this.mergeUseAiInput?.checked || false,
      mergeBaseUrl: this.mergeBaseUrlInput?.value || '',
      mergeApiKey: this.mergeApiKeyInput?.value || '',
      mergeModel: this.mergeModelInput?.value || '',
      mergePrompt: this.mergePromptInput?.value || '',
      mergeReasoningEffort: this.mergeReasoningEffortSelect?.value || '',
      multiSourceEnabled: this.multiSourceEnabledInput?.checked || false,
      msSources: this._getSelectedSources(),
      msMergeMode: this.mergeModeSelect?.value || 'system',
      msMergePrimarySource: this.mergePrimarySourceSelect?.value || '',
      msMergeBaseUrl: this.msMergeBaseUrlInput?.value || '',
      msMergeApiKey: this.msMergeApiKeyInput?.value || '',
      msMergeModel: this.msMergeModelInput?.value || '',
    };
    try { localStorage.setItem('vt_settings', JSON.stringify(s)); } catch (_) { }
    if (!this._debouncedServerSave) {
      this._debouncedServerSave = this._debounce(() => this._saveServerSettings(), 500);
    }
    this._debouncedServerSave();
  }

  _loadSettings() {
    try {
      const raw = localStorage.getItem('vt_settings');
      if (!raw) return;
      const s = JSON.parse(raw);
      if (this.uiLanguages.includes(s.uiLang)) this._savedUiLang = s.uiLang;
      if (s.inputSourceMode === 'file' || s.inputSourceMode === 'url') this.inputSourceMode = s.inputSourceMode;
      if (s.baseUrl) this.modelBaseUrl.value = s.baseUrl;
      if (s.apiKey && !s.apiKey.includes('...')) this.apiKeyInput.value = s.apiKey;
      if (s.reasoningEffort) this.reasoningEffortSelect.value = s.reasoningEffort;
      if (s.summaryLang) this.summaryLangSel.value = s.summaryLang;
      if (s.groqApiKey && !s.groqApiKey.includes('...')) this.groqApiKeyInput.value = s.groqApiKey;
      if (s.groqModel) this.groqModelSelect.value = s.groqModel;
      if (s.groqLanguage) this.groqLanguageInput.value = s.groqLanguage;
      if (s.groqPrompt) this.groqPromptInput.value = s.groqPrompt;
      if (s.transcriptionProvider) this.transcriptionProviderSelect.value = s.transcriptionProvider;
      this.trySubtitlesFirstInput.checked = s.trySubtitlesFirst !== false;
      this.useLocalFallbackInput.checked = Boolean(s.useLocalFallback);
      if (s.localBackend) this.localBackendSelect.value = s.localBackend;
      this._savedLocalModelPreset = s.localModelPreset || '';
      if (s.localModelId) this.localModelIdInput.value = s.localModelId;
      if (s.localLanguage) this.localLanguageInput.value = s.localLanguage;
      if (s.localApiBaseUrl) this.localApiBaseUrlInput.value = s.localApiBaseUrl;
      if (s.localApiKey && !s.localApiKey.includes('...')) this.localApiKeyInput.value = s.localApiKey;
      if (s.localApiModel) this.localApiModelInput.value = s.localApiModel;
      if (s.localApiLanguage) this.localApiLanguageInput.value = s.localApiLanguage;
      if (s.localApiPrompt) this.localApiPromptInput.value = s.localApiPrompt;
      this.includeTimecodesInput.checked = Boolean(s.includeTimecodes);
      if (s.summaryFormat) this.summaryFormatSel.value = s.summaryFormat;
      if (s.summaryPrompt) this.summaryPromptInput.value = s.summaryPrompt;
      if (this.dualLocalInput) this.dualLocalInput.checked = Boolean(s.dualLocal);
      this._savedDualWhisperModelPreset = s.dualWhisperModelPreset || '';
      if (s.dualWhisperModelId && this.dualWhisperModelIdInput) this.dualWhisperModelIdInput.value = s.dualWhisperModelId;
      this._savedDualParakeetModelPreset = s.dualParakeetModelPreset || '';
      if (s.dualParakeetModelId && this.dualParakeetModelIdInput) this.dualParakeetModelIdInput.value = s.dualParakeetModelId;
      if (this.mergeUseAiInput) this.mergeUseAiInput.checked = Boolean(s.mergeUseAi);
      if (s.mergeBaseUrl && this.mergeBaseUrlInput) this.mergeBaseUrlInput.value = s.mergeBaseUrl;
      if (s.mergeApiKey && !s.mergeApiKey.includes('...') && this.mergeApiKeyInput) this.mergeApiKeyInput.value = s.mergeApiKey;
      if (s.mergeModel && this.mergeModelInput) this.mergeModelInput.value = s.mergeModel;
      if (s.mergePrompt && this.mergePromptInput) this.mergePromptInput.value = s.mergePrompt;
      if (s.mergeReasoningEffort && this.mergeReasoningEffortSelect) this.mergeReasoningEffortSelect.value = s.mergeReasoningEffort;
      if (this.multiSourceEnabledInput) this.multiSourceEnabledInput.checked = Boolean(s.multiSourceEnabled);
      if (Array.isArray(s.msSources)) {
        this.sourceCheckboxes.forEach(cb => { cb.checked = s.msSources.includes(cb.value); });
      }
      if (s.msMergeMode && this.mergeModeSelect) this.mergeModeSelect.value = s.msMergeMode;
      if (s.msMergePrimarySource && this.mergePrimarySourceSelect) this.mergePrimarySourceSelect.value = s.msMergePrimarySource;
      if (s.msMergeBaseUrl && this.msMergeBaseUrlInput) this.msMergeBaseUrlInput.value = s.msMergeBaseUrl;
      if (s.msMergeApiKey && !s.msMergeApiKey.includes('...') && this.msMergeApiKeyInput) this.msMergeApiKeyInput.value = s.msMergeApiKey;
      if (s.msMergeModel && this.msMergeModelInput) this._setSelectValue(this.msMergeModelInput, s.msMergeModel);
      if (['md', 'txt', 'pdf'].includes(s.transcriptSaveFormat)) {
        this.saveTranscriptFormatTop.value = s.transcriptSaveFormat;
        this.saveTranscriptFormatBottom.value = s.transcriptSaveFormat;
      }
      if (['md', 'txt', 'pdf'].includes(s.summarySaveFormat)) {
        this.saveSummaryFormatTop.value = s.summarySaveFormat;
        this.saveSummaryFormatBottom.value = s.summarySaveFormat;
      }
      // Model options will be restored after fetching
      this._savedModel = s.model || '';

      // Auto-open settings if credentials were saved
      if (s.baseUrl || s.apiKey || s.groqApiKey || s.localApiBaseUrl || s.transcriptionProvider === 'local' || s.transcriptionProvider === 'local_api' || s.useLocalFallback) {
        this.settingsBody.classList.add('open');
        this.settingsToggle.classList.add('open');
        // Attempt to re-fetch model list silently
        if (s.baseUrl && s.apiKey) {
          setTimeout(() => this._fetchModels(true), 400);
        }
      }
      this._renderSelectedAudioFile();
      this._renderSourceMode();
      this._syncProviderSettings();
    } catch (_) { }
  }

  /* -- Server settings sync -------------------------------------- */
  async _loadServerSettings() {
    try {
      const resp = await fetch(`${this.apiBase}/settings`);
      if (!resp.ok) return;
      const s = await resp.json();
      // Populate config fields from server settings.
      // Credential fields are skipped because the server returns masked values.
      // Credentials come from localStorage (where the real values are stored client-side).
      if (s.openai_base_url) this.modelBaseUrl.value = s.openai_base_url;
      if (s.groq_model) this.groqModelSelect.value = s.groq_model;
      if (s.groq_language) this.groqLanguageInput.value = s.groq_language;
      if (s.groq_prompt) this.groqPromptInput.value = s.groq_prompt;
      if (s.transcription_provider) this.transcriptionProviderSelect.value = s.transcription_provider;
      if (s.summary_language) this.summaryLangSel.value = s.summary_language;
      if (s.summary_format) this.summaryFormatSel.value = s.summary_format;
      if (s.summary_prompt) this.summaryPromptInput.value = s.summary_prompt;
      if (s.reasoning_effort) this.reasoningEffortSelect.value = s.reasoning_effort;
      this.trySubtitlesFirstInput.checked = s.try_subtitles_first !== false;
      this.useLocalFallbackInput.checked = Boolean(s.use_local_fallback);
      if (s.local_backend) this.localBackendSelect.value = s.local_backend;
      if (s.local_model_preset) this.localModelPresetSelect.value = s.local_model_preset;
      if (s.local_model_id) this.localModelIdInput.value = s.local_model_id;
      if (s.local_language) this.localLanguageInput.value = s.local_language;
      if (s.local_api_base_url) this.localApiBaseUrlInput.value = s.local_api_base_url;
      if (s.local_api_key) this.localApiKeyInput.value = s.local_api_key;
      if (s.local_api_model) this.localApiModelInput.value = s.local_api_model;
      if (s.local_api_language) this.localApiLanguageInput.value = s.local_api_language;
      if (s.local_api_prompt) this.localApiPromptInput.value = s.local_api_prompt;
      this.includeTimecodesInput.checked = Boolean(s.include_timecodes);
      if (this.dualLocalInput && s.dual_local_transcription !== undefined) this.dualLocalInput.checked = Boolean(s.dual_local_transcription);
      if (s.dual_whisper_model_preset) this._savedDualWhisperModelPreset = s.dual_whisper_model_preset;
      if (s.dual_whisper_model_id && this.dualWhisperModelIdInput) this.dualWhisperModelIdInput.value = s.dual_whisper_model_id;
      if (s.dual_parakeet_model_preset) this._savedDualParakeetModelPreset = s.dual_parakeet_model_preset;
      if (s.dual_parakeet_model_id && this.dualParakeetModelIdInput) this.dualParakeetModelIdInput.value = s.dual_parakeet_model_id;
      if (this.mergeUseAiInput && s.merge_use_ai !== undefined) this.mergeUseAiInput.checked = Boolean(s.merge_use_ai);
      if (s.merge_base_url && this.mergeBaseUrlInput) this.mergeBaseUrlInput.value = s.merge_base_url;
      if (s.merge_api_key && !s.merge_api_key.includes('...') && this.mergeApiKeyInput) this.mergeApiKeyInput.value = s.merge_api_key;
      if (s.merge_model && this.mergeModelInput) this.mergeModelInput.value = s.merge_model;
      if (s.merge_prompt && this.mergePromptInput) this.mergePromptInput.value = s.merge_prompt;
      if (s.merge_reasoning_effort && this.mergeReasoningEffortSelect) this.mergeReasoningEffortSelect.value = s.merge_reasoning_effort;
      if (s.transcription_sources) {
        try {
          const msSources = JSON.parse(s.transcription_sources);
          if (Array.isArray(msSources)) {
            if (this.multiSourceEnabledInput) this.multiSourceEnabledInput.checked = msSources.length > 0;
            this.sourceCheckboxes.forEach(cb => { cb.checked = msSources.includes(cb.value); });
          }
        } catch (_) {}
      }
      if (s.multi_source_enabled !== undefined && this.multiSourceEnabledInput) {
        this.multiSourceEnabledInput.checked = Boolean(s.multi_source_enabled);
      }
      if (s.merge_mode && this.mergeModeSelect) this.mergeModeSelect.value = s.merge_mode;
      if (s.merge_primary_source && this.mergePrimarySourceSelect) this.mergePrimarySourceSelect.value = s.merge_primary_source;
      this._syncMultiSourceSettings();
      this._syncProviderSettings();
    } catch (_) { }
  }

  _saveServerSettings() {
    const payload = {
      groq_api_key: this.groqApiKeyInput.value.trim(),
      openai_api_key: this.apiKeyInput.value.trim(),
      openai_base_url: this.modelBaseUrl.value.trim(),
      groq_model: this.groqModelSelect.value,
      groq_language: this.groqLanguageInput.value.trim(),
      groq_prompt: this.groqPromptInput.value.trim(),
      transcription_provider: this.transcriptionProviderSelect.value,
      try_subtitles_first: this.trySubtitlesFirstInput.checked,
      use_local_fallback: this.useLocalFallbackInput.checked,
      local_backend: this.localBackendSelect.value,
      local_model_preset: this.localModelPresetSelect.value,
      local_model_id: this.localModelIdInput.value.trim(),
      local_language: this.localLanguageInput.value.trim(),
      local_api_base_url: this.localApiBaseUrlInput.value.trim(),
      local_api_key: this.localApiKeyInput.value.trim(),
      local_api_model: this.localApiModelInput.value.trim(),
      local_api_language: this.localApiLanguageInput.value.trim(),
      local_api_prompt: this.localApiPromptInput.value.trim(),
      include_timecodes: this.includeTimecodesInput.checked,
      summary_language: this.summaryLangSel.value,
      summary_format: this.summaryFormatSel.value,
      summary_prompt: this.summaryPromptInput.value.trim(),
      reasoning_effort: this.reasoningEffortSelect.value,
      dual_local_transcription: this.transcriptionProviderSelect.value === 'local' && !this.multiSourceEnabledInput?.checked && Boolean(this.dualLocalInput?.checked),
      dual_whisper_model_preset: this.dualWhisperModelPresetSelect?.value || 'base',
      dual_whisper_model_id: this.dualWhisperModelIdInput?.value?.trim() || '',
      dual_parakeet_model_preset: this.dualParakeetModelPresetSelect?.value || '',
      dual_parakeet_model_id: this.dualParakeetModelIdInput?.value?.trim() || '',
      merge_use_ai: this.mergeUseAiInput?.checked || false,
      merge_base_url: this.mergeBaseUrlInput?.value?.trim() || '',
      merge_api_key: this.mergeApiKeyInput?.value?.trim() || '',
      merge_model: this.mergeModelInput?.value?.trim() || '',
      merge_prompt: this.mergePromptInput?.value?.trim() || '',
      merge_reasoning_effort: this.mergeReasoningEffortSelect?.value || '',
      multi_source_enabled: this.multiSourceEnabledInput?.checked || false,
      transcription_sources: this.multiSourceEnabledInput?.checked ? JSON.stringify(this._getSelectedSources()) : '',
      merge_mode: this.mergeModeSelect?.value || '',
      merge_primary_source: this.mergePrimarySourceSelect?.value || '',
    };
    fetch(`${this.apiBase}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch(() => { });
  }

  async _fetchLocalCapabilities() {
    try {
      const resp = await fetch(`${this.apiBase}/local-model-capabilities`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      this.localCapabilities = await resp.json();
      this._populateLocalModelPresets();
      this._populateDualModelPresets();
      this._renderLocalCapabilities();
      this._syncProviderSettings();
    } catch (e) {
      console.warn('Local capabilities fetch error:', e);
      this.localCapabilities = null;
      if (this.localCapabilitiesNotice) {
        this.localCapabilitiesNotice.className = 'status-note error';
        this.localCapabilitiesNotice.textContent = this.t('local_capabilities_error');
      }
      if (this.localCapabilitiesDetail) {
        this.localCapabilitiesDetail.className = 'status-note error';
        this.localCapabilitiesDetail.textContent = e.message;
      }
    }
  }

  _backendCapabilities(backend) {
    const backends = this.localCapabilities?.backends || {};
    return backends[backend] || null;
  }

  _populateLocalModelPresets() {
    if (!this.localModelPresetSelect) return;
    const backend = this.localBackendSelect?.value || 'whisper';
    const caps = this._backendCapabilities(backend);
    const presets = Array.isArray(caps?.presets) ? caps.presets : [];
    const fallbackPresets = backend === 'parakeet'
      ? ['nvidia/parakeet-tdt-0.6b-v3', 'nvidia/parakeet-tdt-0.6b-v2']
      : ['tiny', 'base', 'small', 'medium', 'large-v3'];
    const values = presets.length ? presets : fallbackPresets;
    const current = this.localModelPresetSelect.value || this._savedLocalModelPreset || '';

    this.localModelPresetSelect.innerHTML = '';
    values.forEach(value => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      this.localModelPresetSelect.appendChild(option);
    });
    const customOption = document.createElement('option');
    customOption.value = 'custom';
    customOption.textContent = this.t('local_model_custom_option');
    this.localModelPresetSelect.appendChild(customOption);

    const preferred = current && [...values, 'custom'].includes(current)
      ? current
      : (caps?.default_preset || values[0] || 'custom');
    this.localModelPresetSelect.value = preferred;
    this._savedLocalModelPreset = '';
    this._syncProviderSettings();
  }

  _renderLocalCapabilities() {
    const backend = this.localBackendSelect?.value || 'whisper';
    const caps = this._backendCapabilities(backend);
    const runtime = this.localCapabilities?.runtime || 'cpu';
    const runtimeLabel = this.t(runtime === 'cuda' ? 'runtime_cuda' : 'runtime_cpu');

    if (this.localCapabilitiesNotice) {
      this.localCapabilitiesNotice.className = 'status-note';
      this.localCapabilitiesNotice.textContent = `${this.t('local_runtime_notice')}: ${runtimeLabel}`;
    }

    if (!this.localCapabilitiesDetail) return;
    if (!caps) {
      this.localCapabilitiesDetail.className = 'status-note error';
      this.localCapabilitiesDetail.textContent = this.t('local_capabilities_error');
      return;
    }

    const parts = [];
    parts.push(caps.available ? this.t('local_backend_ready') : this.t('local_backend_unavailable'));
    if (!caps.available && caps.auto_install) {
      parts.push(this.t('local_backend_auto_install'));
    }
    if (caps.runtime) {
      parts.push(`${this.t('local_runtime_notice')}: ${this.t(caps.runtime === 'cuda' ? 'runtime_cuda' : 'runtime_cpu')}`);
    }
    if (caps.warning_code === 'parakeet_cpu_slow') {
      parts.push(this.t('parakeet_cpu_warning'));
    } else if (caps.warning) {
      parts.push(caps.warning);
    }
    this.localCapabilitiesDetail.className = `status-note${caps.available ? (caps.warning ? ' warn' : '') : ' error'}`;
    this.localCapabilitiesDetail.replaceChildren();
    parts.forEach((part, index) => {
      if (index > 0) this.localCapabilitiesDetail.append(document.createTextNode(' '));
      if (typeof part === 'string') {
        this.localCapabilitiesDetail.append(document.createTextNode(part));
        return;
      }
      if (part?.type === 'link') {
        const link = document.createElement('a');
        link.href = part.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = part.text;
        this.localCapabilitiesDetail.append(link);
      }
    });
  }

  _syncProviderSettings() {
    const provider = this.transcriptionProviderSelect?.value || 'groq';
    const useFallback = Boolean(this.useLocalFallbackInput?.checked);
    const fileMode = this.inputSourceMode === 'file';
    const showGroq = provider === 'groq';
    const showLocal = provider === 'local' || (provider === 'groq' && useFallback);
    const showLocalApi = provider === 'local_api';
    const showCustomModel = this.localModelPresetSelect?.value === 'custom';

    this.groqSettings?.forEach(el => el.classList.toggle('setting-hidden', !showGroq));
    this.localSettings?.forEach(el => el.classList.toggle('setting-hidden', !showLocal));
    this.localApiSettings?.forEach(el => el.classList.toggle('setting-hidden', !showLocalApi));
    if (this.useLocalFallbackRow) {
      this.useLocalFallbackRow.classList.toggle('setting-hidden', provider !== 'groq');
    }
    if (this.trySubtitlesFirstRow) {
      this.trySubtitlesFirstRow.classList.toggle('setting-hidden', fileMode);
    }
    if (this.localModelCustomRow) {
      this.localModelCustomRow.classList.toggle('setting-hidden', !showLocal || !showCustomModel);
    }

    if (this.groqApiKeyInput) this.groqApiKeyInput.disabled = !showGroq;
    if (this.groqModelSelect) this.groqModelSelect.disabled = !showGroq;
    if (this.groqLanguageInput) this.groqLanguageInput.disabled = !showGroq;
    if (this.groqPromptInput) this.groqPromptInput.disabled = !showGroq;
    if (this.trySubtitlesFirstInput) this.trySubtitlesFirstInput.disabled = fileMode;
    if (this.localBackendSelect) this.localBackendSelect.disabled = !showLocal;
    if (this.localModelPresetSelect) this.localModelPresetSelect.disabled = !showLocal;
    if (this.localModelIdInput) this.localModelIdInput.disabled = !showLocal || !showCustomModel;
    if (this.localLanguageInput) this.localLanguageInput.disabled = !showLocal;
    if (this.localApiBaseUrlInput) this.localApiBaseUrlInput.disabled = !showLocalApi;
    if (this.localApiKeyInput) this.localApiKeyInput.disabled = !showLocalApi;
    if (this.localApiModelInput) this.localApiModelInput.disabled = !showLocalApi;
    if (this.localApiLanguageInput) this.localApiLanguageInput.disabled = !showLocalApi;
    if (this.localApiPromptInput) this.localApiPromptInput.disabled = !showLocalApi;

    this._renderLocalCapabilities();
    this._syncDualSettings();
  }

  _syncDualSettings() {
    const isLocal = (this.transcriptionProviderSelect?.value || 'groq') === 'local';
    if (!isLocal && this.dualLocalInput?.checked) {
      this.dualLocalInput.checked = false;
    }
    const isDual = Boolean(this.dualLocalInput?.checked);
    const showDual = isLocal && isDual;
    const showDualWhisperCustom = this.dualWhisperModelPresetSelect?.value === 'custom';
    const showDualParakeetCustom = this.dualParakeetModelPresetSelect?.value === 'custom';

    if (this.dualLocalRow) this.dualLocalRow.classList.toggle('setting-hidden', !isLocal);
    if (this.dualLocalInput) this.dualLocalInput.disabled = !isLocal;
    this.dualLocalSettings?.forEach(el => el.classList.toggle('setting-hidden', !showDual));
    if (this.dualWhisperCustomRow) this.dualWhisperCustomRow.classList.toggle('setting-hidden', !showDual || !showDualWhisperCustom);
    if (this.dualParakeetCustomRow) this.dualParakeetCustomRow.classList.toggle('setting-hidden', !showDual || !showDualParakeetCustom);
    if (this.dualWhisperModelPresetSelect) this.dualWhisperModelPresetSelect.disabled = !showDual;
    if (this.dualParakeetModelPresetSelect) this.dualParakeetModelPresetSelect.disabled = !showDual;
    if (this.dualWhisperModelIdInput) this.dualWhisperModelIdInput.disabled = !showDual || !showDualWhisperCustom;
    if (this.dualParakeetModelIdInput) this.dualParakeetModelIdInput.disabled = !showDual || !showDualParakeetCustom;
    if (this.trySubtitlesFirstRow) {
      const hideForDual = showDual;
      const hideForFile = (this.inputSourceMode || 'url') === 'file';
      this.trySubtitlesFirstRow.classList.toggle('setting-hidden', hideForDual || hideForFile);
    }
  }

  _syncMultiSourceSettings() {
    const enabled = Boolean(this.multiSourceEnabledInput?.checked);
    const checkedSources = this.sourceCheckboxes.filter(cb => cb.checked).map(cb => cb.value);
    const hasSources = enabled && checkedSources.length > 0;
    const mergeMode = this.mergeModeSelect?.value || 'system';
    const showAiMerge = enabled && mergeMode === 'ai';
    const showPrimary = enabled && mergeMode === 'system' && checkedSources.length > 1;

    if (this.multiSourceProviderPicker) this.multiSourceProviderPicker.classList.toggle('setting-hidden', !enabled);
    this.sourceCheckboxes.forEach(cb => { cb.disabled = !enabled; });
    this.multiSourceSections?.forEach(el => el.classList.toggle('setting-hidden', !hasSources));
    this.msMergeAiSettings?.forEach(el => el.classList.toggle('setting-hidden', !showAiMerge));
    if (this.mergePrimarySourceRow) this.mergePrimarySourceRow.classList.toggle('setting-hidden', !showPrimary);

    // Update primary source dropdown to only show checked sources
    if (this.mergePrimarySourceSelect) {
      const current = this.mergePrimarySourceSelect.value;
      const options = this.mergePrimarySourceSelect.querySelectorAll('option');
      options.forEach(opt => {
        if (!opt.value) return;
        opt.hidden = !checkedSources.includes(opt.value);
      });
      if (current && !checkedSources.includes(current)) {
        this.mergePrimarySourceSelect.value = '';
      }
    }
  }

  _getSelectedSources() {
    if (!this.multiSourceEnabledInput?.checked) return [];
    return this.sourceCheckboxes.filter(cb => cb.checked).map(cb => cb.value);
  }

  _populateDualModelPresets() {
    const whisperCaps = this._backendCapabilities('whisper');
    const parakeetCaps = this._backendCapabilities('parakeet');
    const whisperPresets = Array.isArray(whisperCaps?.presets) ? whisperCaps.presets : ['tiny', 'base', 'small', 'medium', 'large-v3'];
    const parakeetPresets = Array.isArray(parakeetCaps?.presets) ? parakeetCaps.presets : ['nvidia/parakeet-tdt-0.6b-v3', 'nvidia/parakeet-tdt-0.6b-v2'];

    if (this.dualWhisperModelPresetSelect) {
      const current = this.dualWhisperModelPresetSelect.value || this._savedDualWhisperModelPreset || 'base';
      this.dualWhisperModelPresetSelect.innerHTML = '';
      whisperPresets.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v; opt.textContent = v;
        this.dualWhisperModelPresetSelect.appendChild(opt);
      });
      const customOpt = document.createElement('option');
      customOpt.value = 'custom'; customOpt.textContent = this.t('local_model_custom_option');
      this.dualWhisperModelPresetSelect.appendChild(customOpt);
      const preferred = [...whisperPresets, 'custom'].includes(current) ? current : (whisperCaps?.default_preset || 'base');
      this.dualWhisperModelPresetSelect.value = preferred;
      this._savedDualWhisperModelPreset = '';
    }

    if (this.dualParakeetModelPresetSelect) {
      const current = this.dualParakeetModelPresetSelect.value || this._savedDualParakeetModelPreset || '';
      this.dualParakeetModelPresetSelect.innerHTML = '';
      parakeetPresets.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v; opt.textContent = v;
        this.dualParakeetModelPresetSelect.appendChild(opt);
      });
      const customOpt = document.createElement('option');
      customOpt.value = 'custom'; customOpt.textContent = this.t('local_model_custom_option');
      this.dualParakeetModelPresetSelect.appendChild(customOpt);
      const preferred = [...parakeetPresets, 'custom'].includes(current) ? current : (parakeetCaps?.default_preset || parakeetPresets[0] || '');
      this.dualParakeetModelPresetSelect.value = preferred;
      this._savedDualParakeetModelPreset = '';
    }
  }

  /* -- Fetch models ---------------------------------------------- */
  _setSelectValue(selectEl, value) {
    if (!selectEl || !value) return;
    const exists = Array.from(selectEl.options || []).some(opt => opt.value === value);
    if (!exists) {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = value;
      selectEl.appendChild(opt);
    }
    selectEl.value = value;
  }

  async _fetchModels(silent = false) {
    const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
    const apiKey = this.apiKeyInput.value.trim();

    if (!baseUrl || !apiKey) {
      if (!silent) this._setFetchStatus('err', this.t('api_key') + ' & URL required');
      return;
    }

    this.fetchModelsBtn.disabled = true;
    this.fetchIcon.className = 'fas fa-spinner fa-spin';
    if (!silent) this._setFetchStatus('', this.t('fetching_models'));

    try {
      const fd = new FormData();
      fd.append('base_url', baseUrl);
      fd.append('api_key', apiKey);

      const resp = await fetch(`${this.apiBase}/models`, { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const models = data.data || data.models || [];

      // Rebuild select options
      this.modelSelect.innerHTML = `<option value="">${this.t('model_default')}</option>`;
      models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.name || m.id;
        this.modelSelect.appendChild(opt);
      });

      // Restore previously selected model
      if (this._savedModel) {
        this.modelSelect.value = this._savedModel;
        this._savedModel = '';
      }
      this._updateReasoningAvailability();

      this._setFetchStatus('ok', typeof this.t('models_loaded') === 'function'
        ? this.t('models_loaded')(models.length)
        : `${models.length} models`);

    } catch (e) {
      console.warn('Model fetch error:', e);
      this._setFetchStatus('err', this.t('models_error') + ': ' + e.message);
    } finally {
      this.fetchModelsBtn.disabled = false;
      this.fetchIcon.className = 'fas fa-sync-alt';
    }
  }

  _setFetchStatus(cls, msg) {
    this.fetchStatus.className = 'fetch-status' + (cls ? ` ${cls}` : '');
    this.fetchStatus.textContent = msg;
  }

  async _fetchMergeModels(silent = false) {
    const baseUrl = this.msMergeBaseUrlInput?.value.trim().replace(/\/$/, '') || '';
    const apiKey = this.msMergeApiKeyInput?.value.trim() || '';

    if (!baseUrl || !apiKey) {
      if (!silent) this._setMergeFetchStatus('err', this.t('api_key') + ' & URL required');
      return;
    }

    if (this.msMergeFetchModelsBtn) this.msMergeFetchModelsBtn.disabled = true;
    if (this.msMergeFetchIcon) this.msMergeFetchIcon.className = 'fas fa-spinner fa-spin';
    if (!silent) this._setMergeFetchStatus('', this.t('fetching_models'));

    try {
      const current = this.msMergeModelInput?.value || '';
      const fd = new FormData();
      fd.append('base_url', baseUrl);
      fd.append('api_key', apiKey);

      const resp = await fetch(`${this.apiBase}/models`, { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const models = data.data || data.models || [];

      this.msMergeModelInput.innerHTML = `<option value="">${this.t('model_default')}</option>`;
      models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.name || m.id;
        this.msMergeModelInput.appendChild(opt);
      });

      if (current) this._setSelectValue(this.msMergeModelInput, current);

      this._setMergeFetchStatus('ok', typeof this.t('models_loaded') === 'function'
        ? this.t('models_loaded')(models.length)
        : `${models.length} models`);
    } catch (e) {
      console.warn('Merge model fetch error:', e);
      this._setMergeFetchStatus('err', this.t('models_error') + ': ' + e.message);
    } finally {
      if (this.msMergeFetchModelsBtn) this.msMergeFetchModelsBtn.disabled = false;
      if (this.msMergeFetchIcon) this.msMergeFetchIcon.className = 'fas fa-sync-alt';
    }
  }

  _setMergeFetchStatus(cls, msg) {
    if (!this.msMergeFetchStatus) return;
    this.msMergeFetchStatus.className = 'fetch-status' + (cls ? ` ${cls}` : '');
    this.msMergeFetchStatus.textContent = msg;
  }

  _modelSupportsReasoning(modelId) {
    const id = String(modelId || '').toLowerCase().split('/').pop();
    return id.startsWith('gpt-5') || id.startsWith('o1') || id.startsWith('o3') || id.startsWith('o4');
  }

  _updateReasoningAvailability() {
    if (!this.reasoningEffortSelect) return;
    const modelId = this.modelSelect.value;
    if (!modelId) {
      this.reasoningEffortSelect.disabled = true;
      return;
    }
    const supported = this._modelSupportsReasoning(modelId);
    this.reasoningEffortSelect.disabled = !supported;
    if (!supported) this.reasoningEffortSelect.value = '';
  }

  /* -- Transcription --------------------------------------------- */
  async _startTranscription() {
    if (this.submitBtn.disabled) return;

    const url = this.videoUrlInput.value.trim();
    const fileMode = this.inputSourceMode === 'file';
    const audioFile = this.audioFileInput?.files?.[0] || null;
    const sumLang = this.summaryLangSel.value;

    if (fileMode) {
      if (!audioFile) { this._showError(this.t('error_no_audio_file')); return; }
    } else if (!url) {
      this._showError(this.t('error_invalid_url')); return;
    }

    this.currentTask = null;
    this._setLoading(true);
    this._hideError();
    this._showProgress();

    try {
      const fd = new FormData();
      fd.append('url', fileMode ? '' : url);
      if (fileMode && audioFile) fd.append('audio_file', audioFile, audioFile.name);
      fd.append('summary_language', sumLang);

      const apiKey = this.apiKeyInput.value.trim();
      const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
      const modelId = this.modelSelect.value;
      if (apiKey) fd.append('api_key', apiKey);
      if (baseUrl) fd.append('model_base_url', baseUrl);
      if (modelId) fd.append('model_id', modelId);

      const groqKey = this.groqApiKeyInput.value.trim();
      const groqModel = this.groqModelSelect.value;
      const groqLanguage = this.groqLanguageInput.value.trim();
      const groqPrompt = this.groqPromptInput.value.trim();
      const transcriptionProvider = this.transcriptionProviderSelect.value;
      const trySubtitlesFirst = this.trySubtitlesFirstInput.checked;
      const useLocalFallback = this.useLocalFallbackInput.checked;
      const localBackend = this.localBackendSelect.value;
      const localModelPreset = this.localModelPresetSelect.value;
      const localModelId = this.localModelIdInput.value.trim();
      const localLanguage = this.localLanguageInput.value.trim();
      const localApiBaseUrl = this.localApiBaseUrlInput.value.trim().replace(/\/$/, '');
      const localApiKey = this.localApiKeyInput.value.trim();
      const localApiModel = this.localApiModelInput.value.trim();
      const localApiLanguage = this.localApiLanguageInput.value.trim();
      const localApiPrompt = this.localApiPromptInput.value.trim();
      if (groqKey) fd.append('groq_api_key', groqKey);
      if (groqModel) fd.append('groq_model', groqModel);
      if (groqLanguage && !['auto', 'auto-detect', 'autodetect', 'detect'].includes(groqLanguage.toLowerCase())) fd.append('groq_language', groqLanguage);
      if (groqPrompt) fd.append('groq_prompt', groqPrompt);
      fd.append('transcription_provider', transcriptionProvider);
      fd.append('try_subtitles_first', (!fileMode && trySubtitlesFirst) ? 'true' : 'false');
      fd.append('use_local_fallback', useLocalFallback ? 'true' : 'false');
      fd.append('local_backend', localBackend);
      if (localModelPreset) fd.append('local_model_preset', localModelPreset);
      if (localModelId) fd.append('local_model_id', localModelId);
      if (localLanguage && !['auto', 'auto-detect', 'autodetect', 'detect'].includes(localLanguage.toLowerCase())) fd.append('local_language', localLanguage);
      if (localApiBaseUrl) fd.append('local_api_base_url', localApiBaseUrl);
      if (localApiKey) fd.append('local_api_key', localApiKey);
      if (localApiModel) fd.append('local_api_model', localApiModel);
      if (localApiLanguage && !['auto', 'auto-detect', 'autodetect', 'detect'].includes(localApiLanguage.toLowerCase())) fd.append('local_api_language', localApiLanguage);
      if (localApiPrompt) fd.append('local_api_prompt', localApiPrompt);
      fd.append('include_timecodes', this.includeTimecodesInput.checked ? 'true' : 'false');

      const multiSourceEnabled = Boolean(this.multiSourceEnabledInput?.checked);
      const msSources = this._getSelectedSources();
      if (multiSourceEnabled && msSources.length === 0) {
        this._showError('Select at least one transcription source or disable multi-source transcription.');
        this._setLoading(false);
        this._hideProgress();
        return;
      }
      const dualLocal = transcriptionProvider === 'local' && msSources.length === 0 && Boolean(this.dualLocalInput?.checked);
      const dualWhisperModelPreset = this.dualWhisperModelPresetSelect?.value || 'base';
      const dualWhisperModelId = this.dualWhisperModelIdInput?.value?.trim() || '';
      const dualParakeetModelPreset = this.dualParakeetModelPresetSelect?.value || '';
      const dualParakeetModelId = this.dualParakeetModelIdInput?.value?.trim() || '';
      const mergeUseAi = this.mergeUseAiInput?.checked || false;
      const mergeApiKey = this.mergeApiKeyInput?.value?.trim() || '';
      const mergeBaseUrl = this.mergeBaseUrlInput?.value?.trim().replace(/\/$/, '') || '';
      const mergeModel = this.mergeModelInput?.value?.trim() || '';
      const mergePrompt = this.mergePromptInput?.value?.trim() || '';
      const mergeReasoningEffort = this.mergeReasoningEffortSelect?.value || '';
      fd.append('dual_local_transcription', dualLocal ? 'true' : 'false');
      if (dualWhisperModelPreset) fd.append('dual_whisper_model_preset', dualWhisperModelPreset);
      if (dualWhisperModelId) fd.append('dual_whisper_model_id', dualWhisperModelId);
      if (dualParakeetModelPreset) fd.append('dual_parakeet_model_preset', dualParakeetModelPreset);
      if (dualParakeetModelId) fd.append('dual_parakeet_model_id', dualParakeetModelId);
      fd.append('merge_use_ai', mergeUseAi ? 'true' : 'false');
      if (mergeApiKey) fd.append('merge_api_key', mergeApiKey);
      if (mergeBaseUrl) fd.append('merge_base_url', mergeBaseUrl);
      if (mergeModel) fd.append('merge_model', mergeModel);
      if (mergePrompt) fd.append('merge_prompt', mergePrompt);
      if (mergeReasoningEffort) fd.append('merge_reasoning_effort', mergeReasoningEffort);

      // Multi-source fields
      if (msSources.length > 0) {
        fd.append('transcription_sources', JSON.stringify(msSources));
        const msMergeMode = this.mergeModeSelect?.value || 'system';
        fd.append('merge_mode', msMergeMode);
        const msPrimary = this.mergePrimarySourceSelect?.value || '';
        if (msMergeMode === 'system' && msSources.length > 1 && !msPrimary) {
          this._showError('A primary source is required for system merge.');
          this._setLoading(false);
          this._hideProgress();
          return;
        }
        fd.append('merge_primary_source', msPrimary);
        // Multi-source AI merge credentials
        if (msMergeMode === 'ai') {
          const msBaseUrl = this.msMergeBaseUrlInput?.value?.trim().replace(/\/$/, '') || '';
          const msApiKey = this.msMergeApiKeyInput?.value?.trim() || '';
          const msModel = this.msMergeModelInput?.value?.trim() || '';
          if (msBaseUrl) fd.append('merge_base_url', msBaseUrl);
          if (msApiKey) fd.append('merge_api_key', msApiKey);
          if (msModel) fd.append('merge_model', msModel);
        }
      }

      const resp = await fetch(`${this.apiBase}/process-video`, { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Request failed');
      }

      const data = await resp.json();
      this.currentTaskId = data.task_id;

      this._initSP();
      this._updateProgress(5, this.t('preparing'));
      this._startSSE();
      this._saveSettings();

    } catch (err) {
      this._showError(this.t('error_processing_failed') + err.message);
      this._setLoading(false);
      this._hideProgress();
    }
  }

  /* -- SSE ------------------------------------------------------- */
  _startSSE() {
    if (!this.currentTaskId) return;
    this.eventSource = new EventSource(`${this.apiBase}/task-stream/${this.currentTaskId}`);
    this._startStatusPolling();

    this.eventSource.onmessage = (ev) => {
      try {
        const task = JSON.parse(ev.data);
        if (task.type === 'heartbeat') return;
        this._handleTaskUpdate(task);
      } catch (_) { }
    };

    this.eventSource.onerror = async () => {
      this._stopSSE();
      try {
        if (this.currentTaskId) {
          const r = await fetch(`${this.apiBase}/task-status/${this.currentTaskId}`);
          if (r.ok) {
            const task = await r.json();
            this.currentTask = task;
            this._updateProgress(task.progress || 0, task.message || '', true, task);
            if (task?.summary_status === 'completed') {
              this._stopSP(); this._setLoading(false); this._hideProgress();
              this._finishSummaryLoading();
              this._showResults(task);
              this._switchTab('summary');
              return;
            }
            if (task?.summary_status === 'error') {
              this._stopSP(); this._setLoading(false); this._hideProgress();
              this._finishSummaryLoading();
              this._showError(task.summary_error || task.message || 'Summary error');
              return;
            }
            if (task?.summary_status === 'processing') {
              this._finishSummaryLoading();
              this._showError(this.t('error_processing_failed') + 'Summary stream disconnected');
              return;
            }
            if (task?.status === 'completed') {
              this._stopSP(); this._setLoading(false); this._hideProgress();
              this._showResults(task);
              return;
            }
            if (task?.status === 'error') {
              this._stopSP(); this._setLoading(false); this._hideProgress();
              this._showError(task.error || task.message || 'Processing error');
              return;
            }
          }
        }
      } catch (_) { }
      this._showError(this.t('error_processing_failed') + 'SSE disconnected');
      this._setLoading(false);
    };
  }

  _stopSSE() {
    this._stopStatusPolling();
    if (this.eventSource) { this.eventSource.close(); this.eventSource = null; }
  }

  _startStatusPolling() {
    this._stopStatusPolling();
    this.statusPollTimer = setInterval(async () => {
      if (!this.currentTaskId) return;
      try {
        const r = await fetch(`${this.apiBase}/task-status/${this.currentTaskId}`);
        if (!r.ok) return;
        const task = await r.json();
        this._handleTaskUpdate(task);
      } catch (_) { }
    }, 2500);
  }

  _stopStatusPolling() {
    if (this.statusPollTimer) {
      clearInterval(this.statusPollTimer);
      this.statusPollTimer = null;
    }
  }

  _handleTaskUpdate(task) {
    this.currentTask = task;
    this._updateProgress(task.progress, task.message, true, task);

    if (task.summary_status === 'processing') {
      if (this.summaryPrompt) {
        this.summaryPrompt.style.display = 'flex';
        this.summaryPrompt.querySelector('span').textContent = task.message || this.t('generating_summary');
      }
      return;
    }

    if (task.summary_status === 'completed') {
      this._stopSP(); this._stopSSE(); this._setLoading(false); this._hideProgress();
      this._finishSummaryLoading();
      this._showResults(task);
      this._switchTab('summary');
    } else if (task.summary_status === 'error') {
      this._stopSSE();
      this._finishSummaryLoading();
      this._showError(task.summary_error || task.message || 'Summary error');
    } else if (task.status === 'completed') {
      this._stopSP(); this._stopSSE(); this._setLoading(false); this._hideProgress();
      this._showResults(task);
    } else if (task.status === 'error') {
      this._stopSP(); this._stopSSE(); this._setLoading(false); this._hideProgress();
      this._showError(task.error || 'Processing error');
    }
  }

  _finishSummaryLoading() {
    if (!this.generateSummaryBtn) return;
    this.generateSummaryBtn.disabled = false;
    this.generateSummaryBtn.innerHTML = this._summaryButtonOriginal || `<i class="fas fa-wand-magic-sparkles"></i> <span data-i18n="generate_summary">${this.t('generate_summary')}</span>`;
    this._summaryButtonOriginal = null;
  }

  /* -- Progress -------------------------------------------------- */
  _updateProgress(pct, msg, fromServer = false, task = null) {
    if (fromServer) {
      this._stopSP();
      this.sp.lastServer = pct;
      this.sp.current = pct;
      this._renderProgress(pct, msg, task);
      return;
    }
    this.sp.current = pct;
    this._renderProgress(pct, msg, task);
  }

  _setModeBadge(mode) {
    if (!this.modeBadge) return;
    if (mode === 'subtitle') {
      this.modeBadge.textContent = this.t('mode_subtitle');
      this.modeBadge.className = 'mode-badge subtitle';
      this.modeBadge.style.display = 'inline-block';
      if (this.progressFill) this.progressFill.classList.add('subtitle-mode');
    } else if (mode === 'local' || mode === 'whisper') {
      this.modeBadge.textContent = this.t('mode_local');
      this.modeBadge.className = 'mode-badge local';
      this.modeBadge.style.display = 'inline-block';
      if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    } else if (mode === 'fallback') {
      this.modeBadge.textContent = this.t('mode_fallback');
      this.modeBadge.className = 'mode-badge fallback';
      this.modeBadge.style.display = 'inline-block';
      if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    } else if (mode === 'dual_local') {
      this.modeBadge.textContent = this.t('mode_dual_local');
      this.modeBadge.className = 'mode-badge local';
      this.modeBadge.style.display = 'inline-block';
      if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    } else if (mode === 'multi_source') {
      this.modeBadge.textContent = this.t('mode_multi_source');
      this.modeBadge.className = 'mode-badge local';
      this.modeBadge.style.display = 'inline-block';
      if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    } else if (mode === 'local_api') {
      this.modeBadge.textContent = this.t('mode_local_api');
      this.modeBadge.className = 'mode-badge local';
      this.modeBadge.style.display = 'inline-block';
      if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    } else if (mode === 'groq') {
      this.modeBadge.textContent = this.t('mode_groq');
      this.modeBadge.className = 'mode-badge groq';
      this.modeBadge.style.display = 'inline-block';
      if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    } else {
      this.modeBadge.style.display = 'none';
      this.modeBadge.className = 'mode-badge';
      if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    }
  }

  _initSP() {
    this.sp.enabled = false; this.sp.current = 0; this.sp.target = 15;
    this.sp.lastServer = 0; this.sp.startTime = Date.now(); this.sp.stage = 'preparing';
  }
  _startSP() {
    this.sp.enabled = false;
  }
  _stopSP() {
    if (this.sp.interval) { clearInterval(this.sp.interval); this.sp.interval = null; }
    this.sp.enabled = false;
  }

  _stageLabel(code) {
    if (!code) return '';
    const key = `stage_${code}`;
    const translated = this.t(key);
    if (translated && translated !== key) return translated;
    const fallback = code.replaceAll('_', ' ');
    return fallback ? fallback.charAt(0).toUpperCase() + fallback.slice(1) : '';
  }

  _defaultStageSteps(task) {
    if (!task) return [];
    const flow = task.stage_flow || task.transcription_provider_requested || task.transcription_provider_used || 'groq';
    const fileMode = task.input_source_type === 'file';
    if (flow === 'subtitles') return [{ code: 'checking_subtitles' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'local_api') return [{ code: fileMode ? 'reading_uploaded_audio' : 'downloading_audio' }, { code: 'sending_local_api_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'local') return [{ code: fileMode ? 'reading_uploaded_audio' : 'downloading_audio' }, { code: 'preparing_audio' }, { code: 'loading_local_model' }, { code: 'transcribing_local_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'dual_local') return [{ code: 'subtitle_skipped' }, { code: fileMode ? 'reading_uploaded_audio' : 'downloading_audio' }, { code: 'preparing_audio' }, { code: 'transcribing_local_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'multi_source') return [{ code: 'subtitle_skipped' }, { code: fileMode ? 'reading_uploaded_audio' : 'downloading_audio' }, { code: 'preparing_audio' }, { code: 'transcribing_local_audio' }, { code: 'merging_transcripts' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'groq_local_fallback') return [{ code: 'resolving_groq_audio_url' }, { code: 'switching_to_local_fallback' }, { code: 'downloading_audio' }, { code: 'preparing_audio' }, { code: 'loading_local_model' }, { code: 'transcribing_local_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'groq_local_file_fallback') return [{ code: 'reading_uploaded_audio' }, { code: 'uploading_groq_audio' }, { code: 'switching_to_local_fallback' }, { code: 'preparing_audio' }, { code: 'loading_local_model' }, { code: 'transcribing_local_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'groq_file_upload') return [{ code: 'reading_uploaded_audio' }, { code: 'uploading_groq_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'groq_file_fallback') return [{ code: 'resolving_groq_audio_url' }, { code: 'downloading_groq_fallback_audio' }, { code: 'uploading_groq_fallback_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    if (flow === 'groq' && fileMode) return [{ code: 'reading_uploaded_audio' }, { code: 'uploading_groq_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
    return [{ code: 'resolving_groq_audio_url' }, { code: 'transcribing_groq_audio' }, { code: 'saving_transcript' }, { code: 'completed' }];
  }

  _resolveStageData(task) {
    if (!task) return { steps: [], currentIndex: null, stageCode: null };
    const steps = Array.isArray(task.stage_steps) && task.stage_steps.length ? task.stage_steps : this._defaultStageSteps(task);
    const stageCode = task.stage_code || null;
    let currentIndex = Number.isFinite(task.stage_index) ? task.stage_index : null;
    if (!currentIndex && stageCode) {
      const foundIndex = steps.findIndex(step => step && step.code === stageCode);
      currentIndex = foundIndex >= 0 ? foundIndex + 1 : null;
    }
    return { steps, currentIndex, stageCode };
  }

  _stageMode(task) {
    if (!task) return null;
    const flow = task.stage_flow || task.transcription_provider_used || task.transcription_provider_requested;
    if (flow === 'subtitles') return 'subtitle';
    if (flow === 'local_api') return 'local_api';
    if (flow === 'groq_local_fallback' || flow === 'groq_local_file_fallback' || task.used_local_fallback) return 'fallback';
    if (flow === 'dual_local') return 'dual_local';
    if (flow === 'multi_source') return 'multi_source';
    if (flow === 'local') return 'local';
    if (flow === 'groq_file_upload') return 'groq';
    return 'groq';
  }

  _renderStageTimeline(task) {
    if (!this.stageTimeline) return;
    this.stageTimeline.innerHTML = '';
    const { steps, currentIndex, stageCode } = this._resolveStageData(task);
    if (!steps.length) return;

    const isCompleted = task?.status === 'completed' || task?.summary_status === 'completed';
    const isError = task?.status === 'error' || task?.summary_status === 'error';

    steps.forEach((step, index) => {
      const position = index + 1;
      const item = document.createElement('div');
      item.className = 'stage-step';

      if (isError && step.code === stageCode) {
        item.classList.add('error');
      } else if (isCompleted && currentIndex && position <= currentIndex) {
        item.classList.add('complete');
      } else if (currentIndex && position < currentIndex) {
        item.classList.add('complete');
      } else if (currentIndex && position === currentIndex) {
        item.classList.add('active');
      }

      const dot = document.createElement('span');
      dot.className = 'stage-step-dot';
      const label = document.createElement('span');
      label.className = 'stage-step-label';
      label.textContent = this._stageLabel(step.code);
      item.append(dot, label);
      this.stageTimeline.appendChild(item);
    });
  }

  _renderSourceStatuses(task) {
    if (!this.sourceStatusPanel) return;
    const statuses = Array.isArray(task?.source_statuses) ? task.source_statuses : [];
    this.sourceStatusPanel.innerHTML = '';
    this.sourceStatusPanel.classList.toggle('show', statuses.length > 0);
    if (!statuses.length) return;

    const title = document.createElement('div');
    title.className = 'source-status-title';
    title.textContent = this.t('source_status_title');

    const grid = document.createElement('div');
    grid.className = 'source-status-grid';

    statuses.forEach(src => {
      const status = String(src.status || 'pending').toLowerCase();
      const card = document.createElement('div');
      card.className = `source-status-card ${status}`;

      const name = document.createElement('span');
      name.className = 'source-status-name';
      name.textContent = src.label || src.source_id || '';

      const state = document.createElement('span');
      state.className = 'source-status-state';
      const statusKey = `source_status_${status}`;
      const translated = this.t(statusKey);
      state.textContent = translated && translated !== statusKey ? translated : status;

      card.append(name, state);

      if (src.detail) {
        const detail = document.createElement('span');
        detail.className = 'source-status-detail';
        detail.textContent = src.detail;
        card.append(detail);
      }

      grid.appendChild(card);
    });

    this.sourceStatusPanel.append(title, grid);
  }

  _formatStageElapsed(ms) {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) {
      return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  _renderStageElapsed(task = this.currentTask) {
    if (!this.stageElapsed) return;
    const startedAt = task?.stage_started_at ? Date.parse(task.stage_started_at) : NaN;
    const stageTotal = task?.stage_total;
    const stageIndex = task?.stage_index;
    const parts = [];
    if (Number.isFinite(stageIndex) && Number.isFinite(stageTotal)) {
      parts.push(`${stageIndex}/${stageTotal}`);
    }
    if (Number.isFinite(startedAt)) {
      parts.push(`${this.t('stage_elapsed_prefix')}: ${this._formatStageElapsed(Date.now() - startedAt)}`);
    }
    this.stageElapsed.textContent = parts.join(' • ');
  }

  _startStageTimer(task) {
    this._stopStageTimer();
    if (!task?.stage_started_at) {
      this._renderStageElapsed(task);
      return;
    }
    this._renderStageElapsed(task);
    this.stageTimer = setInterval(() => this._renderStageElapsed(this.currentTask), 1000);
  }

  _stopStageTimer() {
    if (this.stageTimer) {
      clearInterval(this.stageTimer);
      this.stageTimer = null;
    }
  }

  _renderProgress(pct, msg, task = null) {
    const p = Math.round(pct * 10) / 10;
    this.progressStatus.textContent = `${p}%`;
    this.progressFill.style.width = `${p}%`;

    if (task) {
      const stageLabel = this._stageLabel(task.stage_code);
      const label = msg || stageLabel || this.t('processing');
      this.progressMessage.textContent = label;
      this._setModeBadge(this._stageMode(task));
      if (this.stageCurrent) {
        this.stageCurrent.textContent = msg && stageLabel && msg !== stageLabel
          ? `${this.t('active_stage')}: ${stageLabel}`
          : (stageLabel ? `${this.t('active_stage')}: ${stageLabel}` : '');
      }
      this._renderStageTimeline(task);
      this._renderSourceStatuses(task);
      this._startStageTimer(task);
      return;
    }

    this.progressMessage.textContent = msg || this.t('processing');
    if (this.stageCurrent) this.stageCurrent.textContent = '';
    if (this.stageTimeline) this.stageTimeline.innerHTML = '';
    if (this.stageElapsed) this.stageElapsed.textContent = '';
    if (this.sourceStatusPanel) {
      this.sourceStatusPanel.innerHTML = '';
      this.sourceStatusPanel.classList.remove('show');
    }
  }

  _showProgress() {
    this._stopStageTimer();
    this.emptyState.style.display = 'none';
    this.resultsPanel.classList.remove('show');
    this.progressPanel.classList.add('show');
    // Reset mode badge & progress bar color for new task
    if (this.modeBadge) { this.modeBadge.style.display = 'none'; this.modeBadge.className = 'mode-badge'; }
    if (this.progressFill) this.progressFill.classList.remove('subtitle-mode');
    if (this.stageCurrent) this.stageCurrent.textContent = '';
    if (this.stageElapsed) this.stageElapsed.textContent = '';
    if (this.stageTimeline) this.stageTimeline.innerHTML = '';
    if (this.sourceStatusPanel) {
      this.sourceStatusPanel.innerHTML = '';
      this.sourceStatusPanel.classList.remove('show');
    }
  }
  _hideProgress() {
    this._stopStageTimer();
    this.progressPanel.classList.remove('show');
    if (this.sourceStatusPanel) {
      this.sourceStatusPanel.innerHTML = '';
      this.sourceStatusPanel.classList.remove('show');
    }
  }

  /* -- Results --------------------------------------------------- */
  _showResults(task) {
    this.currentTask = task || {};
    const script = this.currentTask.transcript || this.currentTask.script;
    const summary = this.currentTask.summary;
    const translation = this.currentTask.translation;
    const detectedLang = this.currentTask.detected_language;
    const summaryLang = this.currentTask.summary_language;

    this.scriptContent.innerHTML = script ? marked.parse(script) : '';
    this.summaryContent.innerHTML = summary ? marked.parse(summary) : '';

    if (this.summaryPrompt) {
      this.summaryPrompt.style.display = summary ? 'none' : 'flex';
    }
    if (this.summaryActionsTop) {
      this.summaryActionsTop.style.display = summary ? 'flex' : 'none';
    }
    if (this.summaryActionsBottom) {
      this.summaryActionsBottom.style.display = summary ? 'flex' : 'none';
    }
    if (this.dlSummary) {
      this.dlSummary.style.display = (this.currentTask.summary_markdown_path || this.currentTask.summary_path) ? 'inline-flex' : 'none';
    }
    if (this.dlSummaryHtml) {
      this.dlSummaryHtml.style.display = this.currentTask.summary_html_path ? 'inline-flex' : 'none';
    }
    if (this.dlSummaryTxt) {
      this.dlSummaryTxt.style.display = this.currentTask.summary_text_path ? 'inline-flex' : 'none';
    }

    const showTranslation = translation && detectedLang && summaryLang && detectedLang !== summaryLang;
    if (showTranslation) {
      this.translationContent.innerHTML = marked.parse(translation);
      this.translationTabBtn.style.display = 'inline-block';
      this.dlTranslation.style.display = 'inline-flex';
    } else {
      this.translationTabBtn.style.display = 'none';
      this.dlTranslation.style.display = 'none';
    }

    this.resultsPanel.classList.add('show');
    this._switchTab('script');
    this.resultsPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async _generateSummary() {
    if (!this.currentTaskId) { this._showError(this.t('error_no_download')); return; }
    if (this.generateSummaryBtn.disabled) return;

    const original = this.generateSummaryBtn.innerHTML;
    this._summaryButtonOriginal = original;
    let waitingForSummary = false;
    this.generateSummaryBtn.disabled = true;
    this.generateSummaryBtn.innerHTML = `<span class="spinner"></span> ${this.t('generating_summary_btn')}`;
    this._hideError();

    try {
      const fd = new FormData();
      fd.append('task_id', this.currentTaskId);
      fd.append('summary_language', this.summaryLangSel.value);
      fd.append('output_format', this.summaryFormatSel.value);
      const summaryPrompt = this.summaryPromptInput.value.trim();
      if (summaryPrompt) fd.append('summary_prompt', summaryPrompt);

      const apiKey = this.apiKeyInput.value.trim();
      const baseUrl = this.modelBaseUrl.value.trim().replace(/\/$/, '');
      const modelId = this.modelSelect.value;
      const reasoningEffort = this._modelSupportsReasoning(modelId) ? this.reasoningEffortSelect.value : '';
      if (apiKey) fd.append('api_key', apiKey);
      if (baseUrl) fd.append('model_base_url', baseUrl);
      if (modelId) fd.append('model_id', modelId);
      if (reasoningEffort) fd.append('reasoning_effort', reasoningEffort);

      const resp = await fetch(`${this.apiBase}/summarize-transcript`, { method: 'POST', body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const task = await resp.json();
      this.currentTask = task;
      this._showResults(task);
      this._switchTab('summary');
      this._saveSettings();

      if (task.summary_status === 'processing') {
        waitingForSummary = true;
        this._startSSE();
        return;
      }
    } catch (e) {
      this._showError(this.t('error_processing_failed') + e.message);
    } finally {
      if (!waitingForSummary) {
        this.generateSummaryBtn.disabled = false;
        this.generateSummaryBtn.innerHTML = original;
        this._summaryButtonOriginal = null;
      }
    }
  }

  _hideResults() { this.resultsPanel.classList.remove('show'); }

  /* -- Tabs ------------------------------------------------------ */
  _switchTab(name) {
    this.tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    this.tabPanes.forEach(p => p.classList.toggle('active', p.id === `${name}Tab`));
  }

  _transcriptMarkdown() {
    return String(this.currentTask?.transcript || this.currentTask?.script || '').trim();
  }

  _summaryMarkdown() {
    return String(this.currentTask?.summary || '').trim();
  }

  _markdownToPlainText(markdown) {
    return String(markdown || '')
      .trim()
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/^[ \t]*[-*_]{3,}[ \t]*$/gm, '')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  _transcriptPlainText() {
    return this._markdownToPlainText(this._transcriptMarkdown());
  }

  _summaryPlainText() {
    return this._markdownToPlainText(this._summaryMarkdown());
  }

  async _copyMarkdownText(markdown, button) {
    const text = this._markdownToPlainText(markdown);
    if (!text) { this._showError(this.t('error_no_download')); return; }

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.position = 'fixed';
        area.style.left = '-9999px';
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        document.body.removeChild(area);
      }
      this._flashCopyButton(button);
    } catch (e) {
      this._showError(`Copy failed: ${e.message}`);
    }
  }

  async _copyTranscriptText(button) {
    return this._copyMarkdownText(this._transcriptMarkdown(), button);
  }

  async _copySummaryText(button) {
    return this._copyMarkdownText(this._summaryMarkdown(), button);
  }

  _flashCopyButton(button) {
    const label = button?.querySelector('span');
    if (!label) return;
    const previous = label.textContent;
    button.classList.add('copied');
    label.textContent = this.t('copied_text');
    setTimeout(() => {
      button.classList.remove('copied');
      label.textContent = previous || this.t('copy_text');
    }, 1200);
  }

  _saveMarkdownFile(markdown, format, prefix) {
    const normalized = format === 'txt' ? 'txt' : format === 'pdf' ? 'pdf' : 'md';
    const title = this.currentTask?.safe_title || 'video';
    const shortId = this.currentTask?.short_id || this.currentTaskId || prefix;
    const filenameBase = `${prefix}_${this._safeFilename(title)}_${this._safeFilename(shortId)}`;

    if (normalized === 'pdf') {
      this._savePdfFromMarkdown(markdown, `${filenameBase}.pdf`);
      return;
    }

    const content = normalized === 'txt' ? this._markdownToPlainText(markdown) : String(markdown || '').trim();
    if (!content) { this._showError(this.t('error_no_download')); return; }

    const filename = `${filenameBase}.${normalized}`;
    const type = normalized === 'txt' ? 'text/plain;charset=utf-8' : 'text/markdown;charset=utf-8';
    const blob = new Blob([`${content}\n`], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async _savePdfFromMarkdown(markdown, filename) {
    const content = String(markdown || '').trim();
    if (!content) { this._showError(this.t('error_no_download')); return; }
    if (!window.html2canvas || !window.jspdf?.jsPDF) {
      this._showError('PDF export is unavailable in this browser session.');
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.style.position = 'fixed';
    wrapper.style.left = '-20000px';
    wrapper.style.top = '0';
    wrapper.style.width = '820px';
    wrapper.style.padding = '36px 42px';
    wrapper.style.background = '#F4F2EB';
    wrapper.style.color = '#191F2F';
    wrapper.style.fontFamily = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    wrapper.style.lineHeight = '1.7';
    wrapper.style.boxSizing = 'border-box';
    wrapper.innerHTML = `
      <style>
        .pdf-markdown { font-size: 14px; color: #191F2F; }
        .pdf-markdown h1 { font-size: 28px; margin: 0 0 16px; }
        .pdf-markdown h2 { font-size: 21px; margin: 28px 0 12px; padding-top: 12px; border-top: 1px solid #B8C2DC; color: #6F7EA4; }
        .pdf-markdown h2:first-child { border-top: 0; padding-top: 0; }
        .pdf-markdown h3 { font-size: 17px; margin: 18px 0 8px; color: #6F7EA4; }
        .pdf-markdown p { margin: 0 0 12px; }
        .pdf-markdown strong { color: #6F7EA4; }
        .pdf-markdown blockquote { margin: 14px 0; padding-left: 12px; border-left: 3px solid #9EABCC; color: #707C9F; }
        .pdf-markdown ul, .pdf-markdown ol { margin: 0 0 14px 20px; }
        .pdf-markdown a { color: #6F7EA4; text-decoration: underline; }
        .pdf-markdown hr { border: 0; border-top: 1px solid #B8C2DC; margin: 16px 0; }
      </style>
      <div class="pdf-markdown">${marked.parse(content)}</div>
    `;
    document.body.appendChild(wrapper);

    try {
      const canvas = await window.html2canvas(wrapper, {
        backgroundColor: '#F4F2EB',
        scale: 2,
        useCORS: true,
      });
      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' });
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 10;
      const usableWidth = pageWidth - margin * 2;
      const usableHeight = pageHeight - margin * 2;
      const imageData = canvas.toDataURL('image/png');
      const imageHeight = (canvas.height * usableWidth) / canvas.width;
      let heightLeft = imageHeight;
      let position = margin;

      pdf.addImage(imageData, 'PNG', margin, position, usableWidth, imageHeight, undefined, 'FAST');
      heightLeft -= usableHeight;

      while (heightLeft > 0) {
        position = margin - (imageHeight - heightLeft);
        pdf.addPage();
        pdf.addImage(imageData, 'PNG', margin, position, usableWidth, imageHeight, undefined, 'FAST');
        heightLeft -= usableHeight;
      }

      pdf.save(filename);
    } catch (e) {
      this._showError(`PDF export failed: ${e.message}`);
    } finally {
      document.body.removeChild(wrapper);
    }
  }

  _saveTranscript(format) {
    return this._saveMarkdownFile(this._transcriptMarkdown(), format, 'transcript');
  }

  _saveSummary(format) {
    return this._saveMarkdownFile(this._summaryMarkdown(), format, 'summary');
  }

  _safeFilename(value) {
    return String(value || 'file').replace(/[<>:"/\\|?*\x00-\x1F]+/g, '_').replace(/\s+/g, '_').slice(0, 90);
  }

  /* -- Download -------------------------------------------------- */
  async _downloadFile(type) {
    if (!this.currentTaskId) { this._showError(this.t('error_no_download')); return; }
    try {
      const r = await fetch(`${this.apiBase}/task-status/${this.currentTaskId}`);
      if (!r.ok) throw new Error('Failed to get task status');
      const task = await r.json();

      let filename;
      if (type === 'script') filename = this._filenameFromPath(task.script_path) || `transcript_${task.safe_title || 'x'}_${task.short_id || 'x'}.md`;
      else if (type === 'summary_md') filename = this._filenameFromPath(task.summary_markdown_path || task.summary_path);
      else if (type === 'summary_html') filename = this._filenameFromPath(task.summary_html_path);
      else if (type === 'summary_txt') filename = this._filenameFromPath(task.summary_text_path);
      else if (type === 'translation') filename = this._filenameFromPath(task.translation_path) || `translation_${task.safe_title || 'x'}_${task.short_id || 'x'}.md`;
      else throw new Error('Unknown type');
      if (!filename) throw new Error(this.t('error_no_download'));

      const a = document.createElement('a');
      a.href = `${this.apiBase}/download/${encodeURIComponent(filename)}`;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      this._showError(this.t('error_download_failed') + e.message);
    }
  }

  _filenameFromPath(path) {
    if (!path) return '';
    return String(path).split(/[\\/]/).pop();
  }

  /* -- UI helpers ------------------------------------------------ */
  _setLoading(on) {
    this.submitBtn.disabled = on;
    this.submitBtn.innerHTML = on
      ? `<span class="spinner"></span> <span data-i18n="processing">${this.t('processing')}</span>`
      : `<i class="fas fa-search"></i> <span data-i18n="start_transcription">${this.t('start_transcription')}</span>`;
  }

  _showError(msg) {
    this.errorMsg.textContent = msg;
    this.errorBanner.classList.add('show');
    this.errorBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  _hideError() { this.errorBanner.classList.remove('show'); }

  _debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }
}

/* -- Boot -------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', () => {
  window.vt = new VideoTranscriber();
});

window.addEventListener('beforeunload', () => {
  if (window.vt?.eventSource) window.vt._stopSSE();
});

