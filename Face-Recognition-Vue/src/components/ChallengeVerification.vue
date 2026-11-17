<template>
    <section class="d-flex flex-column ga-4" style="max-width: 720px; width: 100%; margin: 0 auto">
        <h2 class="text-h5">
            Случайные задания
        </h2>
        <v-chip
            color="warning"
            style="align-self: flex-start"
        >
            Эксперимент · замок не управляется
        </v-chip>
        <v-alert
            type="warning"
            variant="tonal"
        >
            Подмена участника не контролируется · проверка действий без эмбеддингов
        </v-alert>
        <v-checkbox v-model="consent" hide-details :disabled="active || busy"
            label="Участник согласен на проверку лица" />
        <v-switch v-model="preparationMode" hide-details :disabled="active || busy"
            label="Настройка исходного положения · без таймаута подготовки" />
        <div class="d-flex flex-wrap ga-3">
            <v-btn prepend-icon="mdi-play" :disabled="active || !consent || busy" @click="start">Начать проверку</v-btn>
            <v-btn prepend-icon="mdi-stop" variant="outlined" :disabled="!active || busy" @click="cancel">Остановить</v-btn>
        </div>
        <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>
        <v-alert v-if="result.display_available === false" type="warning" variant="tonal">TFT недоступен</v-alert>
        <div aria-live="polite" class="d-flex flex-column ga-3">
            <h3 class="text-h6">{{ instruction }}</h3>
            <v-alert v-if="result.observation_status" :type="['face_lost', 'multiple_faces', 'landmarks_not_detected'].includes(result.observation_status) ? 'warning' : 'info'" variant="tonal">
                {{ observationLabel }}
            </v-alert>
            <span v-if="result.total">Выполнено {{ result.completed || 0 }} из {{ result.total }}</span>
            <v-progress-linear v-if="result.total" :model-value="100 * (result.completed || 0) / result.total" />
            <span v-if="active">{{ result.preparation_mode && result.stage === 'baseline' ? 'Подготовка без ограничения времени' : `Осталось на этап: ${result.remaining_seconds ?? '—'} с` }}</span>
            <div v-if="result.stage === 'baseline' && result.diagnostics" class="d-flex flex-column ga-2">
                <span>{{ preparationReason }}</span>
                <template v-if="result.diagnostics.left_ear != null">
                    <span>EAR: левый {{ result.diagnostics.left_ear.toFixed(3) }} · правый {{ result.diagnostics.right_ear.toFixed(3) }} · пределы {{ result.diagnostics.ear_min }}–{{ result.diagnostics.ear_max }}</span>
                    <span>Положение головы: {{ result.diagnostics.yaw.toFixed(3) }} · модуль меньше {{ result.diagnostics.yaw_limit }}</span>
                    <span>Наблюдений: {{ result.diagnostics.samples || 0 }} / минимум 3 · длительность {{ (result.diagnostics.duration_seconds || 0).toFixed(2) }} с / {{ result.diagnostics.required_seconds ?? '—' }} с</span>
                </template>
            </div>
            <v-alert v-if="result.result" :type="result.result === 'PASS' ? 'success' : 'warning'" variant="tonal">
                {{ result.result === 'PASS' ? 'Задания выполнены · личность не установлена' : reason }}
            </v-alert>
            <span v-if="result.session_id" style="overflow-wrap: anywhere">Сессия: {{ result.session_id }}</span>
            <div v-if="result.reason === 'stale_frame' && result.frame_timing" class="d-flex flex-column ga-2">
                <span>Причина: {{ timingReason }}</span>
                <span v-for="[key, label] in timingFields" :key="key">
                    {{ label }}: {{ result.frame_timing[key] == null ? '—' : result.frame_timing[key].toFixed(1) + ' мс' }}
                </span>
                <span v-for="(value, key) in result.frame_timing.stages_ms" :key="key">
                    {{ ({ image_preparation: 'Подготовка изображения', face_detection: 'Поиск лица', landmarks: 'Ключевые точки', embedding: 'Эмбеддинг' })[key] || key }}: {{ value.toFixed(1) }} мс
                </span>
            </div>
        </div>
    </section>
</template>

<script>
const instructions = {
    BLINK: 'Моргните двумя глазами', TURN_LEFT: 'Поверните голову влево', TURN_RIGHT: 'Поверните голову вправо'
};
const reasons = {
    cancelled: 'Проверка остановлена', timeout: 'Время выполнения задания истекло',
    baseline_timeout: 'Не удалось получить исходное положение: смотрите прямо, глаза открыты',
    face_lost: 'Лицо потеряно', multiple_faces: 'В кадре несколько лиц',
    landmarks_not_detected: 'Не удалось определить точки лица', stale_frame: 'Кадры устарели или приходят слишком редко',
    identity_changed: 'Нарушена непрерывность наблюдения за участником',
    camera_unavailable: 'Камера недоступна', processing_error: 'Ошибка обработки или дисплея'
};
export default {
    data() { return { consent: false, preparationMode: false, busy: false, error: '', result: { stage: 'idle' }, timer: null, controller: null, disposed: false }; },
    computed: {
        observationLabel() {
            if (this.result.observation_status === 'action_detected' && this.result.command !== 'BLINK') {
                return `Голова повёрнута ${this.result.command === 'TURN_LEFT' ? 'влево' : 'вправо'} · удерживайте положение`;
            }
            return ({ waiting_for_face: 'Ожидание первого наблюдения', face_found: 'Лицо найдено · проверяется исходное положение',
                face_lost: 'Лицо не найдено · поиск продолжается', multiple_faces: 'Обнаружено несколько лиц · проверка остановлена',
                landmarks_not_detected: 'Не удалось определить точки лица · поиск продолжается',
                waiting_for_action: 'Лицо найдено · ожидается выполнение команды',
                action_detected: 'Действие обнаружено · удерживайте положение',
                action_confirmed: 'Действие подтверждено · вернитесь в исходное положение',
                waiting_for_return: 'Лицо найдено · ожидается возврат в исходное положение',
                returned_to_neutral: 'Исходное положение восстановлено' })[this.result.observation_status]
                || reasons[this.result.observation_status] || this.result.observation_status;
        },
        timingFields() {
            return [['age_before_processing_ms', 'Возраст до обработки'], ['age_after_processing_ms', 'Возраст после обработки'],
                ['processing_ms', 'Обработка кадра'], ['observation_gap_ms', 'Интервал наблюдений'],
                ['frame_age_limit_ms', 'Предел возраста до обработки'], ['observation_limit_ms', 'Предел возраста после обработки и интервала']];
        },
        timingReason() {
            return ({ non_increasing_sequence: 'Повторный номер кадра', future_frame_timestamp: 'Время кадра в будущем',
                frame_too_old_before_processing: 'Кадр устарел до обработки', future_observation_timestamp: 'Время наблюдения в будущем',
                observation_too_old: 'Кадр устарел после обработки', non_increasing_observation_timestamp: 'Время наблюдения не увеличилось',
                observation_gap_exceeded: 'Превышен интервал между наблюдениями' })[this.result.frame_timing.failure] || this.result.frame_timing.failure;
        },
        active() { return ['starting', 'baseline', 'prompt', 'action', 'return'].includes(this.result.stage); },
        preparationReason() {
            return ({ eyes_not_open: 'Не выполнены условия открытия глаз', head_not_straight: 'Голова не в исходном положении',
                collecting: 'Накопление исходных наблюдений', face_lost: 'Ожидание лица',
                landmarks_not_detected: 'Ожидание корректных точек лица' })[this.result.diagnostics?.reason] || 'Ожидание наблюдений';
        },
        instruction() {
            if (this.result.stage === 'baseline') return 'Смотрите прямо, держите глаза открытыми';
            if (this.result.stage === 'return') return 'Вернитесь в исходное положение';
            return instructions[this.result.command] || ({ idle: 'Ожидание', starting: 'Подготовка', passed: 'Проверка завершена', failed: 'Проверка не пройдена' }[this.result.stage]) || 'Подготовка';
        },
        reason() { return reasons[this.result.reason] || 'Проверка не пройдена'; }
    },
    mounted() { this.poll(); },
    beforeUnmount() {
        this.disposed = true;
        clearTimeout(this.timer);
        this.controller?.abort();
        if (this.active && this.result.session_id) fetch('/api/challenge/cancel', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: this.result.session_id }), keepalive: true
        }).catch(() => {});
    },
    methods: {
        async request(path, body, signal) {
            const response = await fetch(`/api/challenge/${path}`, body === undefined ? { signal } : {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal
            });
            if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error(`API вернул не JSON (HTTP ${response.status})`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || 'Операция не выполнена');
            return data;
        },
        async poll() {
            try {
                if (!this.busy) {
                    this.controller = new AbortController();
                    const result = await this.request('status', undefined, this.controller.signal);
                    if (!this.disposed && !this.busy) this.result = result;
                }
            } catch (error) { if (!this.disposed && error.name !== 'AbortError') this.error = error.message; }
            finally { if (!this.disposed) this.timer = setTimeout(() => this.poll(), 300); }
        },
        async start() { await this.command('start', { consent_confirmed: this.consent, preparation_mode: this.preparationMode }); },
        async cancel() { await this.command('cancel', { session_id: this.result.session_id }); },
        async command(action, body) {
            this.busy = true; this.error = ''; this.controller?.abort();
            try { this.result = await this.request(action, body); }
            catch (error) { this.error = error.message; }
            finally { this.busy = false; }
        }
    }
};
</script>
