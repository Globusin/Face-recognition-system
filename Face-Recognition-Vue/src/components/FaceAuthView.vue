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
            <div v-if="tab == 'auth'" class="d-flex flex-column justify-center w-50 h-100 ga-4 border-md rounded pa-6">
                <div class="w-100 d-flex justify-center">
                    <span style="font-size: 40px; color: #d84315">Камера</span>
                </div>

                <v-divider :thickness="4" variant="dashed"/>

                <div class="d-flex flex-row ga-4">
                    <v-sheet class="panel w-75 h-100" rounded>
                        <v-img
                            :width="600"
                            aspect-ratio="16/9"
                            cover
                            :src="imageSrc"
                            rounded="xl"
                        ></v-img>
                    </v-sheet>

                    <div class="d-flex flex-column justify-sm-space-between">
                        <div class="d-flex flex-column ga-4">
                            <v-card
                                variant="outlined"
                                color="#ffab00"
                            >
                                <v-card-item>
                                    <div>
                                        <div
                                            class="text-label-medium text-uppercase mt-2 mb-3"
                                            style="color: #5d4037"
                                        >
                                            Статус
                                        </div>
                                        <div
                                            class="text-title-large mb-1"
                                            :style="{'color': statusColor}"
                                        >
                                            {{ status }}
                                        </div>
                                    </div>
                                </v-card-item>
                            </v-card>

                            <v-card
                                variant="outlined"
                                color="#ffab00"
                            >
                                <v-card-item>
                                    <div>
                                        <div
                                            class="text-label-medium text-uppercase mt-2 mb-3"
                                            style="color: #5d4037"
                                        >
                                            Последний пользователь
                                        </div>
                                        <div
                                            class="text-title-large mb-1"
                                            :style="{'color': statusColor}"
                                        >
                                            {{ lastUser.name }}
                                        </div>
                                    </div>
                                </v-card-item>
                            </v-card>

                            <v-card
                                variant="outlined"
                                color="#ffab00"
                            >
                                <v-card-item>
                                    <div>
                                        <div
                                            class="text-label-medium text-uppercase mt-2 mb-3"
                                            style="color: #5d4037"
                                        >
                                            Близость
                                        </div>
                                        <div
                                            class="text-title-large mb-1"
                                            :style="{'color': statusColor}"
                                        >
                                            {{ recognitionResult.distance }}
                                        </div>
                                    </div>
                                </v-card-item>
                            </v-card>
                        </div>

                        <v-btn
                            text="Аутентификация"
                            @click="authenticateUser"
                            variant="elevated"
                            color="#d84315"
                        >
                            Аутентификация
                        </v-btn>
                    </div>
                </div>
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
            lastUser: 'Неизвестно',
            recognitionResult: 'Неизвестно',

            headers: [
                { title: 'ID', key: 'id' },
                { title: 'Имя', key: 'name' },
                { title: 'Дата регистрации', key: 'date_registered' },
                { title: 'Действия', key: 'actions', sortable: false }
            ],

            users: [],
            newUserName: '',

            imageSrc: '/tmp_image.jpg',
            statusColor: '#5d4037',

            dialogVisible: false
        };
    },
    async mounted() {
        await this.loadUsers();
    },
    methods: {
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
                this.lastUser = this.users.find(u => u.id == data.user_id);
                
                if (data.status === 'success') {
                    this.status = 'Аутентификация успешна! Предоставляется доступ.';
                    this.imageSrc = `/tmp_image.jpg?t=${new Date().getTime()}`;
                    this.statusColor = '#2e7d32'
                } else {
                    this.status = data.message || 'Аутентификация не удалась';
                    this.imageSrc = null;
                    this.statusColor = '#5d4037'
                }
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

.panel {
    padding: 24px !important;
    height: 100%;
    border: 2px solid #8B4513 !important;
    box-shadow: 4px 4px 0px rgba(139, 69, 19, 0.2);
    transition: all 0.3s ease;
}

.panel:hover {
    box-shadow: 6px 6px 0px rgba(139, 69, 19, 0.3);
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
