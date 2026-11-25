<template>
    <div class="d-flex justify-center w-100 h-100">
        <div class="d-flex flex-column ga-4 border-md rounded pa-6" style="width: min(900px, 100%)">
            <div class="w-100 d-flex justify-space-between align-center flex-wrap ga-2">
                <span class="text-h4 text-deep-orange-darken-3">Камеры</span>
                <div class="d-flex align-center ga-2 flex-wrap">
                    <v-chip :color="cameraStatus.dual_mode_enabled ? 'success' : 'grey'" variant="tonal">
                        {{ cameraStatus.dual_mode_enabled ? 'Две камеры' : 'Одна камера' }}
                    </v-chip>
                    <v-chip variant="outlined">{{ cameraDataLabel }}</v-chip>
                </div>
            </div>

            <v-divider :thickness="4" variant="dashed" />
            <v-btn v-if="!cameraStatus.preview_available" prepend-icon="mdi-camera-cog"
                variant="outlined" @click="$emit('maintenance')">Обслуживание камер</v-btn>
            <v-switch v-model="haarPreview" label="Разметка Haar: основная камера" hide-details
                :disabled="!cameraStatus.preview_available"
                @update:model-value="refreshCameraFrames" />

            <div class="camera-grid ga-4">
                <v-card
                    v-for="camera in cameraCards"
                    :key="camera.role"
                    variant="outlined"
                    style="border-color: #d9a441 !important"
                >
                    <v-card-item>
                        <div class="d-flex justify-space-between align-center flex-wrap ga-3">
                            <div class="d-flex align-center ga-2" style="min-width: 0">
                                <v-icon icon="mdi-video-outline"></v-icon>
                                <span class="text-h6 text-brown-darken-2" style="overflow-wrap: anywhere">{{ camera.title }}</span>
                            </div>
                            <v-chip :color="camera.color" size="small" variant="tonal">
                                {{ camera.statusText }}
                            </v-chip>
                        </div>
                    </v-card-item>
                    <v-chip v-if="haarPreview && camera.role === 'primary'" size="small" class="ma-2" variant="outlined">
                        Диагностический снимок Haar
                    </v-chip>
                    <div class="camera-preview">
                        <img
                            v-if="camera.frameUrl && !camera.frameError"
                            :src="camera.frameUrl"
                            :alt="camera.title"
                            @error="cameraFrameErrors[camera.role] = true"
                        />
                        <div v-else class="camera-preview-empty">
                            <v-icon icon="mdi-camera-off-outline" size="36"></v-icon>
                            <span>{{ cameraStatus.preview_available ? 'Кадр недоступен' : 'Предпросмотр отключён' }}</span>
                        </div>
                    </div>
                    <v-card-text class="camera-metrics ga-3">
                        <div class="d-flex flex-column ga-1">
                            <span class="text-body-2 text-brown">Режим</span>
                            <strong>{{ camera.mode }}</strong>
                        </div>
                        <div class="d-flex flex-column ga-1">
                            <span class="text-body-2 text-brown">FPS</span>
                            <strong>{{ formatNumber(camera.actual_fps) }}</strong>
                        </div>
                        <div class="d-flex flex-column ga-1">
                            <span class="text-body-2 text-brown">Чтение</span>
                            <strong>{{ formatMs(camera.average_read_ms) }}</strong>
                        </div>
                    </v-card-text>
                </v-card>
            </div>

            <div class="pairing-summary ga-3 py-3">
                <div class="d-flex flex-column ga-1">
                    <span class="text-body-2 text-brown">Пар кадров</span>
                    <strong>{{ cameraStatus.pairing.paired_frames }}</strong>
                </div>
                <div class="d-flex flex-column ga-1">
                    <span class="text-body-2 text-brown">Средняя разница получения</span>
                    <strong>{{ formatMs(cameraStatus.pairing.average_delta_ms) }}</strong>
                </div>
                <div class="d-flex flex-column ga-1">
                    <span class="text-body-2 text-brown">Максимальная разница получения</span>
                    <strong>{{ formatMs(cameraStatus.pairing.max_delta_ms) }}</strong>
                </div>
                <div class="d-flex flex-column ga-1">
                    <span class="text-body-2 text-brown">Потери</span>
                    <strong>{{ formatPercent(cameraStatus.pairing.drop_rate) }}</strong>
                </div>
            </div>

            <v-card variant="outlined" color="#ffab00">
                <v-card-item>
                    <div class="w-100 d-flex justify-space-between align-center flex-wrap ga-2">
                        <span class="text-h5 text-brown-darken-2">Текущая попытка</span>
                        <v-chip :color="authChipColor" variant="tonal">{{ authStateLabel }}</v-chip>
                    </div>
                </v-card-item>
                <v-card-text class="auth-grid ga-3">
                    <div class="d-flex flex-column ga-1">
                        <span class="text-body-2 text-brown">Этап</span>
                        <strong>{{ stageLabel }}</strong>
                    </div>
                    <div class="d-flex flex-column ga-1">
                        <span class="text-body-2 text-brown">Итог</span>
                        <strong :class="decisionClass">{{ decisionText }}</strong>
                    </div>
                    <div class="d-flex flex-column ga-1">
                        <span class="text-body-2 text-brown">Длительность</span>
                        <strong>{{ elapsedText }}</strong>
                    </div>
                </v-card-text>
                <v-divider />
                <v-card-text>
                    <div class="text-subtitle-2 text-brown mb-2">Проверки</div>
                    <div class="d-flex flex-column ga-2">
                        <div v-for="check in checkRows" :key="check.name"
                             class="d-flex justify-space-between align-center flex-wrap ga-2">
                            <span>{{ check.label }}</span>
                            <div class="d-flex align-center ga-2">
                                <span v-if="check.reason"
                                      class="text-body-2 text-medium-emphasis">{{ check.reason }}</span>
                                <v-chip size="small" :color="check.color" variant="tonal">{{ check.status }}</v-chip>
                            </div>
                        </div>
                    </div>
                    <div v-if="stereoText" class="mt-3 text-body-2">
                        Объём лица: <strong>{{ stereoText }}</strong>
                    </div>
                    <div v-if="challengeText" class="mt-4 pa-3 rounded bg-orange-lighten-5">
                        <div class="text-body-2 text-brown">Задание</div>
                        <div class="text-h6">{{ challengeText }}</div>
                        <div class="text-body-2">
                            {{ challengeStageText }}<span v-if="challengeSeconds !== null"> · осталось {{ challengeSeconds }} с</span>
                        </div>
                    </div>
                    <div v-if="reasonText" class="mt-3 text-body-2">
                        Причина: <strong>{{ reasonText }}</strong>
                    </div>
                    <div v-if="authUnavailable" class="mt-3 text-body-2 text-warning">
                        Нет связи с Monitor: состояние устарело
                    </div>
                </v-card-text>
            </v-card>
        </div>
    </div>
</template>

<script>
import {
    CHALLENGE_STAGE_LABELS, CHECK_LABELS, COMMAND_LABELS, STEREO_DECISION_LABELS,
    decisionLabel, reasonLabel, stateLabel, statusColor, statusLabel,
} from '../authenticationLabels';

export default {
    name: 'FaceAuthentication',
    emits: ['maintenance'],
    data() {
        return {
            requestController: null,
            haarPreview: false,
            stopped: false,
            statusLoading: false,
            authState: {
                state: 'IDLE',
                decision: null,
                reason: '',
                identity_matched: false,
                checks: {},
                stereo: {},
                challenge: null,
                elapsed_seconds: null,
            },
            authTimer: null,
            authUnavailable: false,

            cameraStatus: {
                preview_available: false,
                source: 'configuration',
                updated_at: null,
                dual_mode_enabled: false,
                cameras: {
                    primary: { status: 'offline' },
                    secondary: { status: 'offline' },
                },
                pairing: {
                    paired_frames: 0,
                    average_delta_ms: null,
                    max_delta_ms: null,
                    drop_rate: 0,
                },
            },

            cameraStatusTimer: null,

            cameraFrameTimer: null,

            cameraFrameUrls: {
                primary: '',
                secondary: '',
            },

            cameraFrameErrors: {
                primary: false,
                secondary: false,
            },
        };
    },
    activated() {
        this.stopped = false;
        this.cameraStatus.preview_available = false;
        this.requestController = new AbortController();
        this.loadCameraStatus();
        this.loadAuthenticationState();
        this.cameraStatusTimer = window.setInterval(this.loadCameraStatus, 5000);
        this.cameraFrameTimer = window.setInterval(this.refreshCameraFrames, 1000);
        this.authTimer = window.setInterval(this.loadAuthenticationState, 1000);
    },
    deactivated() {
        this.stopCameraUpdates();
    },
    beforeUnmount() {
        this.stopCameraUpdates();
    },
    computed: {
        cameraDataLabel() {
            if (this.cameraStatus.source === 'live') {
                return 'Текущие данные';
            }
            if (this.cameraStatus.source === 'diagnostic' && this.cameraStatus.updated_at) {
                return `Диагностика: ${new Date(this.cameraStatus.updated_at).toLocaleString('ru-RU')}`;
            }
            return 'Нет измерений';
        },
        cameraCards() {
            return ['primary', 'secondary'].map((role) => {
                const camera = this.cameraStatus.cameras[role] || {};
                const labels = {
                    online: { text: 'Работает', color: 'success' },
                    error: { text: 'Ошибка', color: 'error' },
                    disabled: { text: 'Отключена', color: 'grey' },
                    offline: { text: 'Не подключена', color: 'warning' },
                };
                const label = labels[camera.status] || labels.offline;

                return {
                    ...camera,
                    role,
                    title: role === 'primary' ? 'Основная камера' : 'Дополнительная камера',
                    statusText: label.text,
                    color: label.color,
                    frameUrl: this.cameraFrameUrls[role],
                    frameError: this.cameraFrameErrors[role],
                    mode: camera.width && camera.height ? `${camera.width} × ${camera.height}` : '—',
                };
            });
        },
        authStateLabel() {
            return stateLabel(this.authState.state);
        },
        authChipColor() {
            const colors = {
                GRANTED: 'success',
                DENIED: 'error',
                ERROR: 'error',
                CHALLENGE: 'warning',
                TRACKING: 'info',
                EVALUATING: 'info',
            };
            return colors[this.authState.state] || 'grey';
        },
        stageLabel() {
            return stateLabel(this.authState.state);
        },
        decisionText() {
            return decisionLabel(this.authState.decision);
        },
        decisionClass() {
            if (this.authState.decision === 'GRANTED') return 'text-success';
            if (this.authState.decision === 'DENIED') return 'text-error';
            return '';
        },
        elapsedText() {
            const value = this.authState.elapsed_seconds;
            return typeof value === 'number' ? `${value.toFixed(1)} с` : '—';
        },
        checkRows() {
            return ['recognition', 'stereo', 'challenge'].map((name) => {
                const check = (this.authState.checks && this.authState.checks[name]) || {};
                return {
                    name,
                    label: CHECK_LABELS[name],
                    status: statusLabel(check.status),
                    color: statusColor(check.status),
                    reason: check.reason ? reasonLabel(check.reason) : '',
                };
            });
        },
        stereoText() {
            const value = this.authState.stereo && this.authState.stereo.decision;
            return value ? (STEREO_DECISION_LABELS[value] || value) : '';
        },
        challengeText() {
            const command = this.authState.challenge && this.authState.challenge.command;
            return command ? (COMMAND_LABELS[command] || command) : '';
        },
        challengeStageText() {
            const stage = this.authState.challenge && this.authState.challenge.stage;
            return stage ? (CHALLENGE_STAGE_LABELS[stage] || stage) : '';
        },
        challengeSeconds() {
            const value = this.authState.challenge && this.authState.challenge.remaining_seconds;
            return typeof value === 'number' ? value : null;
        },
        reasonText() {
            return this.authState.reason ? reasonLabel(this.authState.reason) : '';
        },
    },
    methods: {
        stopCameraUpdates() {
            this.stopped = true;
            this.requestController?.abort();
            window.clearInterval(this.cameraStatusTimer);
            window.clearInterval(this.cameraFrameTimer);
            window.clearInterval(this.authTimer);
            this.cameraStatusTimer = null;
            this.cameraFrameTimer = null;
            this.authTimer = null;
            this.cameraFrameUrls = { primary: '', secondary: '' };
        },
        formatNumber(value) {
            return typeof value === 'number' && value > 0 ? value.toFixed(1) : '—';
        },

        formatMs(value) {
            return typeof value === 'number' ? `${value.toFixed(1)} мс` : '—';
        },

        formatPercent(value) {
            return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—';
        },

        refreshCameraFrames() {
            if (this.stopped || document.hidden) return;
            if (!this.cameraStatus.preview_available) {
                this.cameraFrameUrls = { primary: '', secondary: '' };
                return;
            }
            const timestamp = Date.now();

            for (const role of ['primary', 'secondary']) {
                const camera = this.cameraStatus.cameras[role];
                if (camera?.status !== 'online') {
                    this.cameraFrameUrls[role] = '';
                    continue;
                }

                this.cameraFrameErrors[role] = false;
                const diagnostic = this.haarPreview && role === 'primary' ? '&haar=1' : '';
                this.cameraFrameUrls[role] = `/api/cameras/${role}/frame?t=${timestamp}${diagnostic}`;
            }
        },

        async loadCameraStatus() {
            if (this.stopped || document.hidden || this.statusLoading) return;
            this.statusLoading = true;
            try {
                const response = await fetch('/api/cameras/status', { signal: this.requestController.signal });
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                this.cameraStatus = await response.json();
                if (!this.cameraStatus.preview_available) {
                    this.haarPreview = false;
                    this.cameraFrameUrls = { primary: '', secondary: '' };
                }
            } catch (error) {
                if (this.stopped) return;
                this.cameraStatus.preview_available = false;
                this.cameraFrameUrls = { primary: '', secondary: '' };
                this.cameraStatus.cameras.primary.status = 'error';
                this.cameraStatus.cameras.secondary.status = 'error';
            } finally {
                this.statusLoading = false;
            }
        },

        async loadAuthenticationState() {
            if (this.stopped || document.hidden) return;
            try {
                const response = await fetch('/api/authentication/state', {
                    signal: this.requestController.signal,
                });
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                this.authState = await response.json();
                this.authUnavailable = false;
            } catch (error) {
                if (this.stopped) return;
                this.authUnavailable = true;
            }
        },
    },
};
</script>

<style scoped>
.camera-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
}

.camera-preview {
    width: 100%;
    aspect-ratio: 16 / 9;
    background: #202020;
    overflow: hidden;
}

.camera-preview img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
}

.camera-preview-empty {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: #eeeeee;
}

.camera-metrics,
.result-grid,
.pairing-summary {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
}

.camera-metrics div,
.result-grid div,
.pairing-summary div {
    min-width: 0;
}

.camera-metrics strong,
.result-grid strong,
.pairing-summary strong {
    overflow-wrap: anywhere;
}

.pairing-summary {
    grid-template-columns: repeat(4, minmax(0, 1fr));
}

.auth-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
}

@media (max-width: 700px) {
    .camera-grid,
    .camera-metrics,
    .result-grid,
    .pairing-summary,
    .auth-grid {
        grid-template-columns: 1fr;
    }
}
</style>
