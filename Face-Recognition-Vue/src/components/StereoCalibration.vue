<template>
    <section class="calibration d-flex flex-column ga-4">
        <div class="d-flex align-center justify-space-between flex-wrap ga-3">
            <h2 class="text-h5">Калибровка камер</h2>
            <v-chip :color="state.active ? 'warning' : 'grey'">
                {{ state.active ? 'Распознавание приостановлено' : 'Режим выключен' }}
            </v-chip>
        </div>

        <v-form v-if="!authorized" class="d-flex align-start ga-3" @submit.prevent="connect">
            <v-text-field v-model="token" type="password" label="Токен администратора"
                autocomplete="off" variant="outlined" hide-details />
            <v-btn type="submit" prepend-icon="mdi-login" :loading="busy">Войти</v-btn>
        </v-form>

        <v-alert v-if="error" type="error" variant="tonal" closable @click:close="error = ''">
            {{ error }}
        </v-alert>

        <template v-if="authorized">
            <div class="d-flex align-center ga-3 flex-wrap">
                <v-chip variant="outlined">7 × 7 углов</v-chip>
                <v-chip variant="outlined">Клетка {{ state.active ? state.square_mm : squareMm }} мм</v-chip>
                <v-chip variant="outlined">База стенда 120 мм</v-chip>
                <v-spacer />
                <v-btn icon="mdi-refresh" variant="text" title="Обновить состояние"
                    :disabled="busy" @click="connect" />
            </div>

            <template v-if="!state.active">
                <v-text-field v-model.number="squareMm" type="number" min="0.1" step="0.1"
                    label="Размер клетки новой доски, мм" variant="outlined" hide-details :disabled="busy" />
                <v-checkbox v-model="mountingConfirmed" hide-details
                    label="Камеры закреплены, фокус и размеры доски проверены" />
                <v-btn prepend-icon="mdi-camera-control" :loading="busy" :disabled="!mountingConfirmed || !validSquare"
                    @click="start">Начать новую сессию</v-btn>
            </template>

            <template v-else>
                <div class="d-flex align-center flex-wrap ga-4">
                    <v-chip>Обучающие: {{ state.training_pairs }} / 15</v-chip>
                    <v-chip>Контрольные: {{ state.validation_pairs }} / 3</v-chip>
                    <v-chip v-if="observation" variant="outlined">
                        Рассинхрон {{ observation.delta_ms.toFixed(1) }} мс
                    </v-chip>
                </div>
                <div class="d-flex align-start flex-wrap ga-3">
                    <v-select v-model="rotation" :items="rotations" item-title="title" item-value="value"
                        label="Порядок углов второй камеры" variant="outlined" hide-details
                        :disabled="busy" style="min-width: 240px; flex: 1" @update:model-value="clearObservation" />
                    <v-btn prepend-icon="mdi-camera-refresh" :loading="busy" @click="observe">
                        Обновить пару
                    </v-btn>
                </div>

                <div class="calibration-images">
                    <div v-for="role in roles" :key="role" style="min-width: 0">
                        <div class="d-flex align-center justify-space-between flex-wrap ga-2 mb-2">
                            <strong>{{ role === 'primary' ? 'Основная камера' : 'Дополнительная камера' }}</strong>
                            <v-chip size="small" :color="observation?.found[role] ? 'success' : 'grey'">
                                {{ observation?.found[role] ? '49 углов' : 'Нет доски' }}
                            </v-chip>
                        </div>
                        <div class="calibration-image">
                            <img v-if="observation?.previews[role]" :src="observation.previews[role]"
                                :alt="role === 'primary' ? 'Доска основной камеры' : 'Доска дополнительной камеры'">
                            <v-icon v-else icon="mdi-chess-board" size="48" color="grey" />
                        </div>
                        <v-btn class="mt-2" prepend-icon="mdi-download" variant="outlined"
                            :disabled="!observation || busy" @click="downloadFrame(role)">
                            Скачать исходный кадр
                        </v-btn>
                    </div>
                </div>

                <div class="d-flex flex-wrap align-center ga-4">
                    <v-checkbox v-model="orientationConfirmed" hide-details :disabled="!pairReady || busy"
                        label="Углы 1 и 7 соответствуют одним точкам доски" />
                    <v-switch v-model="validation" hide-details label="Контрольная пара" :disabled="busy" />
                </div>
                <div class="d-flex flex-wrap ga-3">
                    <v-btn prepend-icon="mdi-ruler" :disabled="!pairReady || !orientationConfirmed || !mountingConfirmed || !calibrationId || busy"
                        @click="verifyPair">Проверить без пересчёта</v-btn>
                    <v-btn prepend-icon="mdi-content-save-plus" :disabled="!pairReady || !orientationConfirmed || busy"
                        @click="capture">Сохранить пару</v-btn>
                    <v-btn prepend-icon="mdi-calculator" :loading="calculating"
                        :disabled="busy || state.training_pairs < 15 || state.validation_pairs < 3" @click="calculate">
                        Рассчитать
                    </v-btn>
                    <v-spacer />
                    <v-btn prepend-icon="mdi-stop" variant="outlined" :disabled="busy" @click="finish">
                        Завершить сессию
                    </v-btn>
                </div>
                <v-text-field v-model="calibrationId" label="Номер сохранённой калибровки"
                    variant="outlined" hide-details :disabled="busy" />
                <v-checkbox v-model="mountingConfirmed" hide-details :disabled="busy"
                    label="Крепление, фокус и режим камер не менялись после калибровки" />
            </template>

            <template v-if="state.result">
                <v-divider />
                <div class="d-flex justify-space-between flex-wrap ga-2">
                    <h3 class="text-h6">Результат калибровки</h3>
                    <v-chip :color="state.result.status === 'invalidated' ? 'error' : 'warning'">
                        {{ state.result.status === 'invalidated' ? 'Недействительна' : 'Требует проверки' }}
                    </v-chip>
                </div>
                <span class="text-body-2">{{ new Date(state.result.created_at).toLocaleString('ru-RU') }}</span>
                <div class="calibration-metrics">
                    <div v-for="metric in metrics" :key="metric.label" class="d-flex flex-column ga-1">
                        <span class="text-body-2">{{ metric.label }}</span>
                        <strong>{{ metric.value }}</strong>
                    </div>
                </div>
                <div class="d-flex align-center flex-wrap ga-3">
                    <v-btn prepend-icon="mdi-image-search" :disabled="busy" @click="reviewPair()">
                        Показать контрольные пары
                    </v-btn>
                    <v-select v-if="review" :model-value="review.pair_index" :items="review.pair_indices"
                        label="Контрольная пара" hide-details variant="outlined" :disabled="busy"
                        style="max-width: 240px" @update:model-value="reviewPair" />
                    <span v-if="review?.delta_ms != null">Рассинхрон {{ review.delta_ms.toFixed(1) }} мс</span>
                </div>
                <div v-if="review || state.rectified_previews" class="calibration-images">
                    <div v-for="role in roles" :key="role" class="calibration-image">
                        <img :src="(review?.previews || state.rectified_previews)[role]" :alt="`Ректификация: ${role}`">
                    </div>
                </div>
            </template>
            <div v-if="geometry" class="calibration-metrics">
                <div v-for="metric in geometryMetrics" :key="metric.label" class="d-flex flex-column ga-1">
                    <span>{{ metric.label }}</span><strong>{{ metric.value }}</strong>
                </div>
            </div>
        </template>
    </section>
</template>

<script>
export default {
    name: 'StereoCalibration',
    data() {
        return {
            token: '', authorized: false, busy: false, calculating: false, error: '',
            mountingConfirmed: false, orientationConfirmed: false, validation: false,
            rotation: 0, observation: null, review: null, geometry: null, calibrationId: '', squareMm: 45, roles: ['primary', 'secondary'],
            rotations: [0, 1, 2, 3].map(value => ({ value, title: `${value * 90}°` })),
            state: { active: false, session_id: null, training_pairs: 0, validation_pairs: 0, result: null }
        };
    },
    computed: {
        validSquare() {
            return typeof this.squareMm === 'number' && Number.isFinite(this.squareMm) && this.squareMm > 0;
        },
        geometryMetrics() {
            if (!this.geometry) return [];
            return [['Средняя сторона клетки', 'mean_length_mm', 'мм'],
                [`Средняя ошибка относительно ${this.geometry.expected_mm} мм`, 'mean_error_mm', 'мм'],
                ['Максимальная ошибка', 'max_error_mm', 'мм'],
                ['Средняя относительная ошибка', 'mean_error_percent', '%']]
                .map(([label, key, unit]) => ({ label, value: `${Number(this.geometry[key]).toFixed(2)} ${unit}` }));
        },
        pairReady() {
            return this.observation?.found.primary && this.observation?.found.secondary;
        },
        metrics() {
            const m = this.state.result?.metrics;
            if (!m) return [];
            return [
                ['Основная RMS', m.primary_rms_px, 'px'],
                ['Дополнительная RMS', m.secondary_rms_px, 'px'],
                ['Стерео RMS', m.stereo_rms_px, 'px'],
                ['Контроль: среднее по вертикали', m.validation_vertical_mean_px, 'px'],
                ['Контроль: максимум по вертикали', m.validation_vertical_max_px, 'px'],
                ['Контроль: репроекция второй камеры', m.validation_reprojection_mean_px, 'px'],
                ['Расчётная база', m.baseline_mm, 'мм']
            ].map(([label, value, unit]) => ({ label, value: `${Number(value).toFixed(2)} ${unit}` }));
        }
    },
    methods: {
        async verifyPair() {
            this.geometry = null;
            const data = await this.request('verify', { session_id: this.state.session_id,
                observation_id: this.observation?.observation_id, calibration_id: this.calibrationId,
                orientation_confirmed: this.orientationConfirmed, mounting_confirmed: this.mountingConfirmed });
            if (data) this.geometry = data.geometry;
        },
        async reviewPair(pairIndex = null) {
            this.review = null;
            this.geometry = null;
            const data = await this.request('review', {
                session_id: this.state.result?.session_id, pair_index: pairIndex
            });
            if (data) { this.review = data; this.geometry = data.geometry; }
        },
        async readJson(response) {
            if (!(response.headers.get('Content-Type') || '').includes('application/json')) {
                throw new Error(`API вернул не JSON (HTTP ${response.status}). Проверьте, запущен ли backend на порту 5000; также возможна ошибка сервера или устаревший маршрут`);
            }
            return response.json();
        },
        async downloadFrame(role) {
            if (this.busy || !this.observation) return;
            this.busy = true;
            this.error = '';
            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), 30000);
            try {
                const response = await fetch(`/api/calibration/frame/${role}`, {
                    method: 'POST',
                    headers: { 'X-Calibration-Token': this.token, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: this.state.session_id,
                        observation_id: this.observation.observation_id }),
                    signal: controller.signal
                });
                if (!response.ok) {
                    const data = await this.readJson(response);
                    throw new Error(data.message || `HTTP ${response.status}`);
                }
                if (!(response.headers.get('Content-Type') || '').includes('image/png')) {
                    throw new Error('Вместо PNG получен другой ответ. Проверьте backend и прокси API');
                }
                const url = URL.createObjectURL(await response.blob());
                const link = document.createElement('a');
                link.href = url;
                link.download = `calibration_${this.observation.observation_id}_${role}.png`;
                document.body.appendChild(link);
                link.click();
                link.remove();
                window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            } catch (error) {
                this.error = error.name === 'AbortError' ? 'Время скачивания истекло' : error.message;
            } finally {
                window.clearTimeout(timeout);
                this.busy = false;
            }
        },
        clearObservation() {
            this.observation = null;
            this.orientationConfirmed = false;
            this.geometry = null;
        },
        async request(action, body) {
            if (this.busy) return null;
            this.busy = true;
            this.error = '';
            const controller = new AbortController();
            const timeout = window.setTimeout(() => controller.abort(), action === 'calculate' ? 180000 : 30000);
            try {
                const response = await fetch(`/api/calibration/${action}`, {
                    method: body ? 'POST' : 'GET',
                    headers: { 'X-Calibration-Token': this.token, 'Content-Type': 'application/json' },
                    body: body ? JSON.stringify(body) : undefined,
                    signal: controller.signal
                });
                const data = await this.readJson(response);
                if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
                return data;
            } catch (error) {
                this.error = error.name === 'AbortError' ? 'Время ожидания истекло. Обновите состояние сессии' : error.message;
                return null;
            } finally {
                window.clearTimeout(timeout);
                this.busy = false;
            }
        },
        async connect() {
            const data = await this.request('status');
            if (data) { this.authorized = true; this.state = data; this.geometry = null; this.review = null;
                if (data.result?.session_id) this.calibrationId = data.result.session_id; }
        },
        async start() {
            const data = await this.request('start', { mounting_confirmed: this.mountingConfirmed, square_mm: this.squareMm });
            if (data) { this.state = data; this.review = null; this.mountingConfirmed = false; this.clearObservation(); }
        },
        async observe() {
            this.clearObservation();
            const data = await this.request('observe', { session_id: this.state.session_id, rotation: this.rotation });
            if (data) this.observation = data;
        },
        async capture() {
            const data = await this.request('capture', {
                session_id: this.state.session_id, observation_id: this.observation?.observation_id,
                validation: this.validation, orientation_confirmed: this.orientationConfirmed
            });
            if (data) { this.state = data; this.clearObservation(); }
        },
        async calculate() {
            this.geometry = null;
            this.review = null;
            this.calculating = true;
            const data = await this.request('calculate', { session_id: this.state.session_id });
            if (data) this.state = data;
            this.calculating = false;
        },
        async finish() {
            const data = await this.request('finish', { session_id: this.state.session_id });
            if (data) { this.state = data; this.clearObservation(); }
        }
    }
};
</script>

<style scoped>
.calibration { width: min(1100px, 100%); margin: 0 auto; }
.calibration-images { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.calibration-image { display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 16 / 9; background: #202020; overflow: hidden; }
.calibration-image img { display: block; width: 100%; height: 100%; object-fit: contain; }
.calibration-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; overflow-wrap: anywhere; }
@media (max-width: 700px) {
    .calibration-images, .calibration-metrics { grid-template-columns: 1fr; }
}
</style>
