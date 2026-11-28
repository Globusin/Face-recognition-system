<template>
    <section class="entry-screen" aria-labelledby="entry-title">
        <div class="entry-intro">
            <h1 id="entry-title">Проход через систему</h1>
            <p>Встаньте перед камерой и следуйте указаниям на экране.</p>
        </div>
        <v-card variant="outlined" class="entry-status" role="status" aria-live="polite">
            <v-icon :icon="entryIcon" :color="entryColor" size="64" />
            <h2>{{ entryTitle }}</h2>
            <p>{{ entryHint }}</p>
            <v-progress-linear v-if="!unavailable && ['TRACKING', 'EVALUATING'].includes(auth.state)"
                indeterminate color="primary" class="mt-5" />
            <div v-if="!unavailable && auth.state === 'CHALLENGE' && seconds !== null" class="entry-time">
                Осталось {{ seconds }} с
            </div>
        </v-card>
        <p class="entry-note">Проверка начинается автоматически. Нажимать ничего не нужно.</p>
    </section>
</template>

<script>
import {
    CHALLENGE_STAGE_LABELS, CHECK_LABELS, COMMAND_LABELS, STEREO_DECISION_LABELS,
    decisionLabel, reasonLabel, stateLabel, statusColor, statusLabel,
} from '../authenticationLabels';

export default {
    name: 'StatusPanel',
    
    data() {
        return {
            auth: {
                state: 'IDLE',
                decision: null,
                reason: '',
                checks: {},
                stereo: {},
                challenge: null,
            },
            timer: null,
            unavailable: false,
            loaded: false,
            loading: false,
            controller: null,
        };
    },

    computed: {
        entryTitle() {
            if (!this.loaded && !this.unavailable) return 'Подключение…';
            if (this.unavailable || this.auth.state === 'ERROR') return 'Система недоступна';
            if (this.auth.state === 'GRANTED' && !this.auth.door_open) return 'Проверка завершена';
            if (this.auth.state === 'CHALLENGE') return this.challengeText || 'Следуйте указаниям';
            return ({ IDLE: 'Готово к проходу', TRACKING: 'Смотрим на камеру', EVALUATING: 'Идёт проверка', GRANTED: 'Доступ разрешён', DENIED: 'Доступ не разрешён', COOLDOWN: 'Подождите' })[this.auth.state] || 'Ожидание';
        },
        entryHint() {
            if (!this.loaded && !this.unavailable) return 'Получаем состояние устройства.';
            if (this.unavailable || this.auth.state === 'ERROR') return 'Обратитесь к администратору, если связь не восстановится.';
            if (this.auth.state === 'GRANTED' && !this.auth.door_open) return 'Дождитесь следующей попытки.';
            return ({ IDLE: 'Подойдите к камере и смотрите прямо.', TRACKING: 'Держите лицо в кадре.', EVALUATING: 'Не отходите от камеры.', CHALLENGE: 'Выполните действие, затем смотрите прямо.', GRANTED: 'Можно проходить.', DENIED: 'Попробуйте ещё раз после завершения попытки.', COOLDOWN: 'Система готовится к следующей попытке.' })[this.auth.state] || 'Следуйте указаниям на устройстве.';
        },
        entryColor() {
            if (this.unavailable || ['ERROR', 'DENIED'].includes(this.auth.state)) return 'error';
            return this.auth.state === 'GRANTED' ? 'success' : 'primary';
        },
        entryIcon() {
            if (this.unavailable || this.auth.state === 'ERROR') return 'mdi-alert-circle-outline';
            return ({ GRANTED: 'mdi-check-circle-outline', DENIED: 'mdi-close-circle-outline', CHALLENGE: 'mdi-face-recognition', COOLDOWN: 'mdi-clock-outline' })[this.auth.state] || 'mdi-face-recognition';
        },
        chipColor() {
            const colors = {
                GRANTED: 'success',
                DENIED: 'error',
                ERROR: 'error',
                CHALLENGE: 'warning',
                TRACKING: 'info',
                EVALUATING: 'info',
            };
            return colors[this.auth.state] || 'grey';
        },
        decisionClass() {
            if (this.auth.decision === 'GRANTED') return 'text-success';
            if (this.auth.decision === 'DENIED') return 'text-error';
            return 'text-medium-emphasis';
        },
        checks() {
            return ['recognition', 'stereo', 'challenge'].map((name) => {
                const check = (this.auth.checks && this.auth.checks[name]) || {};
                return {
                    label: CHECK_LABELS[name],
                    status: statusLabel(check.status),
                    color: statusColor(check.status),
                };
            });
        },
        stereoText() {
            const value = this.auth.stereo && this.auth.stereo.decision;
            return value ? (STEREO_DECISION_LABELS[value] || value) : '';
        },
        challengeText() {
            const command = this.auth.challenge && this.auth.challenge.command;
            return command ? (COMMAND_LABELS[command] || command) : '';
        },
        challengeStageText() {
            const stage = this.auth.challenge && this.auth.challenge.stage;
            return stage ? (CHALLENGE_STAGE_LABELS[stage] || stage) : '';
        },
        seconds() {
            const value = this.auth.challenge && this.auth.challenge.remaining_seconds;
            return typeof value === 'number' ? value : null;
        },
    },

    mounted() {
        this.load();
        this.timer = window.setInterval(this.load, 1000);
    },

    beforeUnmount() {
        window.clearInterval(this.timer);
        this.controller?.abort();
    },

    methods: {
        stateLabel,
        decisionLabel,
        reasonLabel,
        async load() {
            if (document.hidden || this.loading) return;
            this.loading = true;
            this.controller = new AbortController();
            const timeout = window.setTimeout(() => this.controller?.abort(), 4000);
            try {
                const response = await fetch('/api/authentication/state', { cache: 'no-store', signal: this.controller.signal });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.auth = await response.json();
                this.unavailable = false;
                this.loaded = true;
            } catch (error) {
                this.unavailable = true;
            } finally {
                window.clearTimeout(timeout);
                this.controller = null;
                this.loading = false;
            }
        },
    },
};
</script>

<style scoped>
.entry-screen { width: min(600px, 100%); margin: clamp(32px, 9vh, 100px) auto; padding: 0 16px; text-align: center; }
.entry-intro h1 { font-size: 28px; font-weight: 650; }
.entry-intro p, .entry-note { color: #56616c; margin-top: 10px; }
.entry-status { padding: clamp(24px, 6vw, 48px); margin: 28px 0 16px; min-height: 260px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.entry-status h2 { font-size: clamp(24px, 4vw, 32px); line-height: 1.3; margin: 20px 0 8px; }
.entry-status p { color: #465360; max-width: 38ch; }
.entry-time { font-variant-numeric: tabular-nums; margin-top: 16px; }
.entry-note { font-size: 14px; }
</style>
