<template>
    <div class="d-flex flex-column ga-4">
        <v-card variant="outlined" color="#ffab00" class="status-card">
            <v-card-item>
                <div class="w-100 d-flex justify-space-between align-center flex-wrap ga-3">
                    <span class="text-h5 text-brown-darken-2">Аутентификация</span>
                    <v-chip :color="chipColor" variant="tonal">{{ stateLabel(auth.state) }}</v-chip>
                </div>
            </v-card-item>
            <v-card-text class="d-flex flex-column ga-4">
                <div class="text-h4" :class="decisionClass">{{ decisionLabel(auth.decision) }}</div>
                <div v-if="auth.reason" class="text-body-1">
                    Причина: <strong>{{ reasonLabel(auth.reason) }}</strong>
                </div>
                <div v-if="challengeText" class="pa-4 rounded bg-orange-lighten-5">
                    <div class="text-body-2 text-brown">Задание</div>
                    <div class="text-h5">{{ challengeText }}</div>
                    <div class="text-body-2">
                        {{ challengeStageText }}<span v-if="seconds !== null"> · осталось {{ seconds }} с</span>
                    </div>
                </div>
                <div class="d-flex flex-column ga-2">
                    <div v-for="check in checks" :key="check.label"
                         class="d-flex justify-space-between align-center ga-3">
                        <span>{{ check.label }}</span>
                        <v-chip size="small" :color="check.color" variant="tonal">{{ check.status }}</v-chip>
                    </div>
                </div>
                <div v-if="stereoText" class="text-body-2 text-medium-emphasis">
                    Объём лица: {{ stereoText }}
                </div>
                <div v-if="unavailable" class="text-warning text-body-2">
                    Нет связи с Monitor: состояние устарело
                </div>
            </v-card-text>
        </v-card>
        <div class="text-center">
            <v-btn to="/face-auth" variant="text" prepend-icon="mdi-shield-account">
                Панель администратора
            </v-btn>
        </div>
    </div>
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
        };
    },

    computed: {
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
    },

    methods: {
        stateLabel,
        decisionLabel,
        reasonLabel,
        async load() {
            if (document.hidden) return;
            try {
                const response = await fetch('/api/authentication/state');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.auth = await response.json();
                this.unavailable = false;
            } catch (error) {
                this.unavailable = true;
            }
        },
    },
};
</script>

<style scoped>
.status-card {
    width: min(720px, 100%);
    align-self: center;
}
</style>
