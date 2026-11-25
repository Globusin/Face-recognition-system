<template>
    <div class="d-flex flex-column ga-6">
        <v-card variant="outlined" >
            <v-card-item>
                <div class="w-100 d-flex justify-space-between align-center flex-wrap ga-2">
                    <span class="text-h5 text-brown-darken-2">Журнал доступов</span>
                    <div class="d-flex align-center ga-2 flex-wrap">
                        <v-select
                            v-model="decision"
                            :items="decisionOptions"
                            label="Решение"
                            density="compact"
                            hide-details
                            style="min-width: 170px"
                            @update:model-value="loadHistory"
                        />
                        <v-btn icon="mdi-refresh" aria-label="Обновить журнал" variant="text" :loading="loading" @click="loadHistory" />
                    </div>
                </div>
            </v-card-item>
            <v-card-text>
                <div v-if="error" class="text-error">{{ error }}</div>
                <div v-else-if="!items.length" class="text-medium-emphasis">
                    Записей пока нет. Журнал заполняется после каждой попытки.
                </div>
                <div v-else class="history-table">
                    <v-table density="compact">
                        <thead>
                            <tr>
                                <th>Время</th>
                                <th>Решение</th>
                                <th>Причина</th>
                                <th>Проверки</th>
                                <th>Пользователь</th>
                                <th>Длительность</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="item in items" :key="item.session_id + item.timestamp">
                                <td class="text-no-wrap">{{ formatTime(item.timestamp) }}</td>
                                <td>
                                    <v-chip size="small" :color="decisionColor(item.decision)" variant="tonal">
                                        {{ decisionLabel(item.decision) }}
                                    </v-chip>
                                </td>
                                <td>{{ reasonLabel(item.reason) }}</td>
                                <td>
                                    <div v-for="(check, name) in item.checks" :key="name" class="text-body-2">
                                        {{ checkLabel(name) }}: {{ statusLabel(check.status) }}
                                        <span v-if="check.reason" class="text-medium-emphasis">
                                            ({{ reasonLabel(check.reason) }})
                                        </span>
                                    </div>
                                    <div v-if="item.stereo_decision" class="text-body-2 text-medium-emphasis">
                                        Объём: {{ stereoLabel(item.stereo_decision) }}
                                    </div>
                                </td>
                                <td>{{ userLabel(item.user_id) }}</td>
                                <td class="text-no-wrap">
                                    {{ typeof item.duration_seconds === 'number' ? item.duration_seconds + ' с' : '—' }}
                                </td>
                            </tr>
                        </tbody>
                    </v-table>
                </div>
            </v-card-text>
        </v-card>

        <v-card variant="outlined">
            <v-card-item>
                <span class="text-h5 text-brown-darken-2">Политика аутентификации</span>
            </v-card-item>
            <v-card-text class="d-flex flex-column ga-4">
                <v-select v-model="policy.stereo_mode" :items="stereoOptions" label="Стереопроверка" />
                <v-select v-model="policy.challenge_mode" :items="challengeOptions" label="Задания" />
                <v-text-field
                    v-model.number="policy.challenge_count"
                    type="number"
                    min="1"
                    max="5"
                    label="Заданий на попытку"
                    hint="Одно задание укладывается в тайм-аут сессии"
                    persistent-hint
                />
                <div class="d-flex align-center ga-3 flex-wrap">
                    <v-btn color="primary" variant="elevated" :loading="saving" @click="savePolicy">
                        Сохранить политику
                    </v-btn>
                    <span v-if="saved" class="text-success">Сохранено</span>
                    <span v-if="restartRequired" class="text-warning">
                        Применится после перезапуска Monitor
                    </span>
                </div>
                <div v-if="policyError" class="text-error">{{ policyError }}</div>
                <div class="text-body-2 text-medium-emphasis">
                    Изменение настроек защиты фиксируется в журнале и требует перезапуска,
                    чтобы не менять правила посреди попытки.
                </div>
            </v-card-text>
        </v-card>
    </div>
</template>

<script>
import {
    CHECK_LABELS,
    STEREO_DECISION_LABELS,
    decisionColor,
    decisionLabel,
    reasonLabel,
    statusLabel,
} from '../authenticationLabels';

export default {
    name: 'AccessHistory',
    data() {
        return {
            decision: '',
            decisionOptions: [
                { title: 'Все', value: '' },
                { title: 'Допуск', value: 'GRANTED' },
                { title: 'Отказ', value: 'DENIED' },
                { title: 'Ошибка', value: 'ERROR' },
            ],
            items: [],
            loading: false,
            error: '',
            users: {},
            policy: { stereo_mode: 'advisory', challenge_mode: 'disabled', challenge_count: 1 },
            stereoOptions: [
                { title: 'Выключена', value: 'off' },
                { title: 'Наблюдение (advisory)', value: 'advisory' },
                { title: 'Обязательная (required)', value: 'required' },
            ],
            challengeOptions: [
                { title: 'Выключены', value: 'disabled' },
                { title: 'По слабым доказательствам (adaptive)', value: 'adaptive' },
                { title: 'Всегда (always)', value: 'always' },
            ],
            policyError: '',
            saving: false,
            saved: false,
            restartRequired: false,
        };
    },
    created() {
        this.loadHistory();
        this.loadUsers();
        this.loadPolicy();
    },
    methods: {
        decisionLabel,
        decisionColor,
        reasonLabel,
        statusLabel,
        checkLabel(name) {
            return CHECK_LABELS[name] || name;
        },
        stereoLabel(value) {
            return STEREO_DECISION_LABELS[value] || value || '—';
        },
        formatTime(value) {
            return value ? new Date(value).toLocaleString('ru-RU') : '—';
        },
        userLabel(userId) {
            if (!userId) return '—';
            return this.users[userId] || `#${userId}`;
        },
        async loadHistory() {
            this.loading = true;
            this.error = '';
            try {
                const query = new URLSearchParams({ limit: '100' });
                if (this.decision) query.set('decision', this.decision);
                const response = await fetch(`/api/authentication/history?${query}`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                this.items = Array.isArray(data.items) ? data.items : [];
            } catch (error) {
                this.error = 'Не удалось загрузить журнал';
            } finally {
                this.loading = false;
            }
        },
        async loadUsers() {
            try {
                const response = await fetch('/api/get_users');
                if (!response.ok) return;
                const users = await response.json();
                const mapped = {};
                for (const user of users) {
                    mapped[user.id] = user.username || user.name || `#${user.id}`;
                }
                this.users = mapped;
            } catch (error) {
                this.users = {};
            }
        },
        async loadPolicy() {
            this.policyError = '';
            try {
                const response = await fetch('/api/authentication/policy');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                this.policy = { ...this.policy, ...data.policy };
                this.restartRequired = Boolean(data.restart_required);
            } catch (error) {
                this.policyError = 'Не удалось загрузить политику';
            }
        },
        async savePolicy() {
            this.saving = true;
            this.saved = false;
            this.policyError = '';
            try {
                const response = await fetch('/api/authentication/policy', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        stereo_mode: this.policy.stereo_mode,
                        challenge_mode: this.policy.challenge_mode,
                        challenge_count: Number(this.policy.challenge_count),
                    }),
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || `HTTP ${response.status}`);
                this.saved = true;
                this.restartRequired = Boolean(data.restart_required);
            } catch (error) {
                this.policyError = error.message || 'Не удалось сохранить политику';
            } finally {
                this.saving = false;
            }
        },
    },
};
</script>

<style scoped>
.history-table {
    overflow-x: auto;
}
</style>
