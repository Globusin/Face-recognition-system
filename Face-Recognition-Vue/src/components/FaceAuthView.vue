<template>
    <div class="d-flex flex-column ga-6">
        <!-- TABS -->
        <div class="d-flex justify-center">
            <v-tabs
                v-model="tab"
                inset
            >
                <v-tab value="auth">
                    <div class="tab-content">
                        <v-icon icon="mdi-face-recognition"></v-icon>
                        <span>Аутентификация</span>
                    </div>
                </v-tab>
                <v-tab value="users">
                    <div class="tab-content">
                        <v-icon icon="mdi-account-group"></v-icon>
                        <span>Пользователи</span>
                    </div>
                </v-tab>
            </v-tabs>
        </div>

        <div class="d-flex justify-center w-100 h-100">

            <!-- AUTH -->
            <div v-if="tab == 'auth'" class="d-flex flex-column ga-4 border-md rounded pa-6" style="width: min(900px, 100%)">
                <div class="w-100 d-flex justify-space-between align-center flex-wrap ga-2">
                    <span class="text-h4 text-deep-orange-darken-3">Камеры</span>
                    <div class="d-flex align-center ga-2 flex-wrap">
                        <v-chip
                            :color="cameraStatus.dual_mode_enabled ? 'success' : 'grey'"
                            variant="tonal"
                        >
                            {{ cameraStatus.dual_mode_enabled ? 'Две камеры' : 'Одна камера' }}
                        </v-chip>
                        <v-chip variant="outlined">{{ cameraDataLabel }}</v-chip>
                    </div>
                </div>

                <v-divider :thickness="4" variant="dashed"/>

                <div class="camera-grid ga-4">
                    <v-card
                        v-for="camera in cameraCards"
                        :key="camera.role"
                        variant="outlined"
                        style="border-color: #d9a441 !important"
                    >
                        <v-card-item>
                            <div class="d-flex justify-space-between align-center ga-3">
                                <div class="d-flex align-center ga-2">
                                    <v-icon icon="mdi-video-outline"></v-icon>
                                    <span class="text-h6 text-brown-darken-2">{{ camera.title }}</span>
                                </div>
                                <v-chip :color="camera.color" size="small" variant="tonal">
                                    {{ camera.statusText }}
                                </v-chip>
                            </div>
                        </v-card-item>
                        <div class="camera-preview">
                            <img
                                v-if="camera.frameUrl && !camera.frameError"
                                :src="camera.frameUrl"
                                :alt="camera.title"
                                @error="cameraFrameErrors[camera.role] = true"
                            >
                            <div v-else class="camera-preview-empty">
                                <v-icon icon="mdi-camera-off-outline" size="36"></v-icon>
                                <span>Кадр недоступен</span>
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
                        <span class="text-body-2 text-brown">Средний рассинхрон</span>
                        <strong>{{ formatMs(cameraStatus.pairing.average_delta_ms) }}</strong>
                    </div>
                    <div class="d-flex flex-column ga-1">
                        <span class="text-body-2 text-brown">Максимальный рассинхрон</span>
                        <strong>{{ formatMs(cameraStatus.pairing.max_delta_ms) }}</strong>
                    </div>
                    <div class="d-flex flex-column ga-1">
                        <span class="text-body-2 text-brown">Потери</span>
                        <strong>{{ formatPercent(cameraStatus.pairing.drop_rate) }}</strong>
                    </div>
                </div>

                <v-card variant="outlined" color="#ffab00">
                    <v-card-text class="result-grid ga-3">
                        <div class="d-flex flex-column ga-1">
                            <span class="text-body-2 text-brown">Статус</span>
                            <strong :style="{'color': statusColor}">{{ status }}</strong>
                        </div>
                        <div class="d-flex flex-column ga-1">
                            <span class="text-body-2 text-brown">Последний пользователь</span>
                            <strong>{{ lastUser.name }}</strong>
                        </div>
                        <div class="d-flex flex-column ga-1">
                            <span class="text-body-2 text-brown">Близость</span>
                            <strong>{{ recognitionResult.distance }}</strong>
                        </div>
                    </v-card-text>
                </v-card>

                <v-btn
                    @click="authenticateUser"
                    variant="elevated"
                    color="#d84315"
                    prepend-icon="mdi-face-recognition"
                >
                    Аутентификация
                </v-btn>
            </div>
        
            <!-- USERS -->
            <div v-if="tab == 'users'" class="d-flex flex-column justify-center w-50 h-100 ga-4 border-md rounded pa-6">
                <div class="w-100 d-flex justify-space-between align-center">
                    <span style="font-size: 30px; color: #d84315">Пользователи</span>

                    <v-btn
                        text="Аутентификация"
                        @click="() => dialogVisible = true"
                        variant="elevated"
                        color="#d84315"
                    >
                        Добавить
                    </v-btn>
                </div>

                <v-divider :thickness="4" variant="dashed"/>

                <v-data-table
                    :headers="headers"
                    :items="users"
                    :items-per-page="10"
                    class="custom-table"
                >
                    <template v-slot:item.actions="{ item }">
                        <v-btn
                            color="error"
                            @click="deleteUser(item.id)"
                            class="delete-btn"
                        >
                            Удалить
                        </v-btn>
                    </template>
                </v-data-table>
            </div>
        </div>

        <v-dialog v-model="dialogVisible" max-width="500">
            <v-card>
                <v-card-title class="text-h5" style="color: #d84315">
                    Регистрация нового пользователя
                </v-card-title>
                
                <v-card-text>
                    <p class="mb-4">
                        Для добавления нового пользователя необходимо встать перед камерой.
                    </p>
                    
                    <v-text-field
                        v-model="newUserName"
                        label="Введите имя пользователя"
                        placeholder="Иван Иванов"
                        variant="outlined"
                        color="#d84315"
                        @keyup.enter="addUser"
                    ></v-text-field>
                </v-card-text>

                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn color="grey-darken-1" variant="text" @click="() => dialogVisible = false">
                        Отмена
                    </v-btn>
                    <v-btn color="#d84315" variant="elevated" @click="addUser">
                        Подтвердить и добавить
                    </v-btn>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
export default {
    name: 'FaceAuthView',
    data() {
        return {
            tab: 'auth',

            status: 'Неизвестно',
            lastUser: { name: 'Неизвестно' },
            recognitionResult: { distance: '—' },

            headers: [
                { title: 'ID', key: 'id' },
                { title: 'Имя', key: 'name' },
                { title: 'Дата регистрации', key: 'date_registered' },
                { title: 'Действия', key: 'actions', sortable: false }
            ],

            users: [],
            newUserName: '',

            statusColor: '#5d4037',

            cameraStatus: {
                source: 'configuration',
                updated_at: null,
                dual_mode_enabled: false,
                cameras: {
                    primary: { status: 'offline' },
                    secondary: { status: 'offline' }
                },
                pairing: {
                    paired_frames: 0,
                    average_delta_ms: null,
                    max_delta_ms: null,
                    drop_rate: 0
                }
            },
            cameraStatusTimer: null,
            cameraFrameTimer: null,
            cameraFrameUrls: {
                primary: '',
                secondary: ''
            },
            cameraFrameErrors: {
                primary: false,
                secondary: false
            },

            dialogVisible: false
        };
    },
    async mounted() {
        await Promise.all([this.loadUsers(), this.loadCameraStatus()]);
        this.refreshCameraFrames();
        this.cameraStatusTimer = window.setInterval(this.loadCameraStatus, 5000);
        this.cameraFrameTimer = window.setInterval(this.refreshCameraFrames, 1000);
    },
    beforeUnmount() {
        if (this.cameraStatusTimer) {
            window.clearInterval(this.cameraStatusTimer);
        }
        if (this.cameraFrameTimer) {
            window.clearInterval(this.cameraFrameTimer);
        }
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
                    offline: { text: 'Не подключена', color: 'warning' }
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
                    mode: camera.width && camera.height
                        ? `${camera.width} × ${camera.height}`
                        : '—'
                };
            });
        }
    },
    methods: {
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
            const timestamp = Date.now();

            for (const role of ['primary', 'secondary']) {
                const camera = this.cameraStatus.cameras[role];
                if (camera?.status !== 'online') {
                    this.cameraFrameUrls[role] = '';
                    continue;
                }

                this.cameraFrameErrors[role] = false;
                this.cameraFrameUrls[role] = `/api/cameras/${role}/frame?t=${timestamp}`;
            }
        },

        async loadCameraStatus() {
            try {
                const response = await fetch('/api/cameras/status');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                this.cameraStatus = await response.json();
            } catch (error) {
                this.cameraStatus.cameras.primary.status = 'error';
                this.cameraStatus.cameras.secondary.status = 'error';
            }
        },

        async loadUsers() {
            try {
                const response = await fetch('/api/get_users');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                this.users = data;
            } catch (error) {
                console.error('Ошибка загрузки пользователей:', error);
                this.status = 'Ошибка загрузки пользователей';
            }
        },
        
        async authenticateUser() {
            this.status = 'Выполняется аутентификация...';
            
            try {
                const response = await fetch('/api/authenticate', { method: 'POST' });
                const data = await response.json();

                this.recognitionResult = data
                this.lastUser = this.users.find(u => u.id == data.user_id) || { name: 'Неизвестно' };
                
                if (data.status === 'success') {
                    this.status = 'Личность подтверждена';
                    this.statusColor = '#2e7d32'
                } else {
                    this.status = data.message || 'Аутентификация не удалась';
                    this.statusColor = '#5d4037'
                }
                await this.loadCameraStatus();
            } catch (error) {
                this.status = 'Ошибка соединения';
            }
        },
        
        async addUser() {
            this.status = 'Добавление нового пользователя...';

            try {
                const response = await fetch(`/api/add_user?name=${encodeURIComponent(this.newUserName)}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                const data = await response.json();

                if (data.status === 'success') {
                    this.status = data.message;
                    // Обновляем список пользователей
                    this.loadUsers();
                } else {
                    this.status = data.message || 'Не удалось добавить пользователя';
                }
            } catch (error) {
                this.status = 'Ошибка соединения';
            } finally {
                this.dialogVisible = false;
            }
        },

        
        async deleteUser(userId) {
            if (confirm('Вы уверены, что хотите удалить этого пользователя?')) {
                try {
                    const response = await fetch(`/api/delete_user/${userId}`, { method: 'DELETE' });
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        // Обновляем список пользователей
                        this.users = this.users.filter(user => user.id !== userId);
                    } else {
                        alert(data.message || 'Не удалось удалить пользователя');
                    }
                } catch (error) {
                    alert('Ошибка соединения');
                }
            }
        }
    }
};
</script>

<style scoped>
.tab-content {
    display: flex;
    gap: 8px;
    align-items: center;
    font-weight: 600;
    color: #361904;
}

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

@media (max-width: 700px) {
    .camera-grid,
    .camera-metrics,
    .result-grid,
    .pairing-summary {
        grid-template-columns: 1fr;
    }
}

.custom-table {
    background-color: #FFFFFF !important;
    border: 2px solid #8B4513 !important;
    box-shadow: none;
}

.custom-table :deep(th) {
    background-color: #F5DEB3 !important;
    color: #8B4513 !important;
    font-weight: bold;
    border-bottom: 2px solid #8B4513 !important;
}

.custom-table :deep(td) {
    background-color: #FFFFFF !important;
    color: #5a4a3a;
    border-bottom: 1px solid #DEB887 !important;
}

.custom-table :deep(tr:nth-child(even)) {
    background-color: #FAF8F5 !important;
}

.custom-table :deep(tr:hover) {
    background-color: #FFF8DC !important;
}

.delete-btn {
    background-color: #CD5C5C !important;
    color: #FFFFFF !important;
    text-transform: none;
    border: 2px solid #8B0000;
    box-shadow: 2px 2px 0px rgba(139, 0, 0, 0.3);
}

.delete-btn:hover {
    background-color: #DC143C !important;
    box-shadow: 3px 3px 0px rgba(139, 0, 0, 0.4);
}
</style>
