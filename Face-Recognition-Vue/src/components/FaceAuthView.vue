<template>
  <div class="izba-container">
    <!-- TABS -->
    <v-tabs
      v-model="tab"
      color="#8B4513"
      slider-color="#8B4513"
      inset
      class="izba-tabs"
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
  
    <!-- AUTH -->
    <div v-if="tab == 'auth'" class="izba-row">
      <v-sheet class="izba-panel" rounded>
          <div class="panel-header">
            <v-icon icon="mdi-face-recognition" class="izba-icon"></v-icon>
            <span class="panel-title">Распознавание лица</span>
          </div>

          <p class="panel-text">Нажмите кнопку для аутентификации через распознавание лица</p>

          <v-btn text="Аутентификация" @click="authenticateUser" class="izba-btn">Аутентификация</v-btn>
      </v-sheet>

      <v-sheet class="izba-panel" rounded>
        <div class="status-block">
          <span class="status-label">Статус</span>
          <span class="status-value">{{ status }}</span>
        </div>
      </v-sheet>
    </div>
  
    <!-- USERS -->
    <div v-if="tab == 'users'" class="izba-row">
      <v-sheet class="izba-panel izba-panel-small" rounded>
        <div class="panel-header">
          <v-icon icon="mdi-account-plus" class="izba-icon"></v-icon>
          <span class="panel-title">Добавить пользователя</span>
        </div>

        <p class="panel-text">Зарегистрировать новое лицо в системе</p>

        <v-text-field 
          label="Введите имя" 
          variant="outlined" 
          v-model="newUserName"
          class="izba-input"
        ></v-text-field>

        <v-btn text="Добавить" @click="addUser(newUserName)" class="izba-btn izba-btn-full">
          <template #prepend>
            <v-icon icon="mdi-account-plus"></v-icon>
          </template>
          Добавить
        </v-btn>
      </v-sheet>

      <v-sheet class="izba-panel" rounded>
        <span class="panel-title-small">Зарегистрированные пользователи</span>

        <v-data-table
          :headers="headers"
          :items="users"
          :items-per-page="10"
          class="izba-table"
        >
          <template v-slot:item.actions="{ item }">
            <v-btn
              color="error"
              size="small"
              @click="deleteUser(item.id)"
              class="izba-delete-btn"
            >
              Удалить
            </v-btn>
          </template>
        </v-data-table>
      </v-sheet>
    </div>
  </div>
</template>

<script>
export default {
  name: 'FaceAuthView',
  data() {
    return {
      tab: 'users',
      status: '',
      headers: [
        { title: 'ID', key: 'id' },
        { title: 'Имя', key: 'name' },
        { title: 'Дата регистрации', key: 'date_registered' },
        { title: 'Действия', key: 'actions', sortable: false }
      ],
      users: [],
      newUserName: ''
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
        
        if (data.status === 'success') {
          this.status = 'Аутентификация успешна! Предоставляется доступ.';
        } else {
          this.status = data.message || 'Аутентификация не удалась';
        }
      } catch (error) {
        this.status = 'Ошибка соединения';
      }
    },
    
    async addUser(name) {
      this.status = 'Добавление нового пользователя...';

      try {
        const response = await fetch(`/api/add_user?name=${encodeURIComponent(name)}`, {
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
/* Основной контейнер в стиле русской избы */
.izba-container {
  display: flex;
  flex-direction: column;
  gap: 2vh;
  background-color: #FFFFFF;
  font-family: 'Georgia', serif;
}

/* Tabs styling */
.izba-tabs {
  background-color: #FFFFFF;
  border-bottom: 3px solid #8B4513;
}

.tab-content {
  display: flex;
  gap: 8px;
  align-items: center;
  font-family: 'Georgia', serif;
  font-weight: 600;
  color: #8B4513;
}

/* Row layout */
.izba-row {
  display: flex;
  gap: 16px;
}

/* Panel styling - белые панели с деревянными акцентами */
.izba-panel {
  padding: 24px !important;
  height: 100%;
  background-color: #FFFFFF !important;
  border: 2px solid #8B4513 !important;
  box-shadow: 4px 4px 0px rgba(139, 69, 19, 0.2);
  transition: all 0.3s ease;
}

.izba-panel:hover {
  box-shadow: 6px 6px 0px rgba(139, 69, 19, 0.3);
}

.izba-panel-small {
  width: 30%;
}

/* Panel header */
.panel-header {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 16px;
}

.panel-title {
  font-size: 24px;
  font-weight: bold;
  color: #8B4513;
  font-family: 'Georgia', serif;
}

.panel-title-small {
  font-size: 18px;
  font-weight: bold;
  color: #8B4513;
  font-family: 'Georgia', serif;
  display: block;
  margin-bottom: 12px;
}

.izba-icon {
  color: #8B4513;
}

/* Text styling */
.panel-text {
  color: #5a4a3a;
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 16px;
  font-family: 'Georgia', serif;
}

/* Button styling */
.izba-btn {
  background-color: #8B4513 !important;
  color: #FFFFFF !important;
  font-family: 'Georgia', serif;
  font-weight: 600;
  text-transform: none;
  border: 2px solid #654321;
  box-shadow: 2px 2px 0px rgba(101, 67, 33, 0.5);
  transition: all 0.2s ease;
}

.izba-btn:hover {
  background-color: #A0522D !important;
  box-shadow: 3px 3px 0px rgba(101, 67, 33, 0.6);
  transform: translate(-1px, -1px);
}

.izba-btn:active {
  transform: translate(1px, 1px);
  box-shadow: 1px 1px 0px rgba(101, 67, 33, 0.4);
}

.izba-btn-full {
  width: 100%;
}

/* Status block */
.status-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-label {
  font-size: 14px;
  color: #8B4513;
  font-weight: 600;
  font-family: 'Georgia', serif;
}

.status-value {
  font-size: 16px;
  color: #5a4a3a;
  font-family: 'Georgia', serif;
}

/* Input field styling */
.izba-input :deep(.v-field) {
  background-color: #FFFFFF !important;
  border: 2px solid #8B4513 !important;
}

.izba-input :deep(.v-field--focused) {
  border-color: #A0522D !important;
}

.izba-input :deep(.v-label) {
  color: #8B4513;
  font-family: 'Georgia', serif;
}

/* Table styling */
.izba-table {
  background-color: #FFFFFF !important;
  border: 2px solid #8B4513 !important;
  box-shadow: none;
}

.izba-table :deep(th) {
  background-color: #F5DEB3 !important;
  color: #8B4513 !important;
  font-weight: bold;
  font-family: 'Georgia', serif;
  border-bottom: 2px solid #8B4513 !important;
}

.izba-table :deep(td) {
  background-color: #FFFFFF !important;
  color: #5a4a3a;
  font-family: 'Georgia', serif;
  border-bottom: 1px solid #DEB887 !important;
}

.izba-table :deep(tr:nth-child(even)) {
  background-color: #FAF8F5 !important;
}

.izba-table :deep(tr:hover) {
  background-color: #FFF8DC !important;
}

.izba-delete-btn {
  background-color: #CD5C5C !important;
  color: #FFFFFF !important;
  font-family: 'Georgia', serif;
  text-transform: none;
  border: 2px solid #8B0000;
  box-shadow: 2px 2px 0px rgba(139, 0, 0, 0.3);
}

.izba-delete-btn:hover {
  background-color: #DC143C !important;
  box-shadow: 3px 3px 0px rgba(139, 0, 0, 0.4);
}
</style>
