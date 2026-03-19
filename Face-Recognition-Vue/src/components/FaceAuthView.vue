<template>
  <div class="container">
    <h1>Добро пожаловать!</h1>
    <p>Для доступа к сети выполните аутентификацию через систему распознавания лица.</p>
    
    <div :class="['status', statusClass]">{{ status }}</div>
    
    <button @click="authenticateUser()" class="auth-button">Аутентифицироваться</button>
    <button @click="addUser()" class="add-user-button">Добавить нового пользователя</button>
    
    <div id="result">{{ result }}</div>
  </div>
</template>

<script>
export default {
  name: 'FaceAuthView',
  data() {
    return {
      status: 'Готово к аутентификации',
      statusClass: 'info',
      result: ''
    };
  },
  methods: {
    async authenticateUser() {
      this.status = 'Выполняется аутентификация...';
      this.statusClass = 'info';
      
      try {
        const response = await fetch('/api/authenticate', { method: 'POST' });
        const data = await response.json();
        
        if (data.status === 'success') {
          this.status = 'Аутентификация успешна! Предоставляется доступ к сети.';
          this.statusClass = 'success';
          
          // Через 2 секунды перенаправляем пользователя
          setTimeout(() => {
            window.location.href = 'http://www.google.com';
          }, 2000);
        } else {
          this.status = data.message || 'Аутентификация не удалась';
          this.statusClass = 'error';
        }
      } catch (error) {
        this.status = 'Ошибка соединения';
        this.statusClass = 'error';
      }
    },
    
    async addUser() {
      this.status = 'Добавление нового пользователя...';
      this.statusClass = 'info';
      
      try {
        const response = await fetch('/api/add_user', { method: 'POST' });
        const data = await response.json();
        
        if (data.status === 'success') {
          this.status = data.message;
          this.statusClass = 'success';
        } else {
          this.status = data.message || 'Не удалось добавить пользователя';
          this.statusClass = 'error';
        }
      } catch (error) {
        this.status = 'Ошибка соединения';
        this.statusClass = 'error';
      }
    }
  }
};
</script>

<style scoped>
.container {
  max-width: 500px;
  margin: 0 auto;
  background: white;
  padding: 30px;
  border-radius: 10px;
  box-shadow: 0 0 10px rgba(0,0,0,0.1);
  text-align: center;
  font-family: Arial, sans-serif;
  margin-top: 50px;
}

button {
  background-color: #4CAF50;
  color: white;
  padding: 15px 32px;
  text-align: center;
  text-decoration: none;
  display: inline-block;
  font-size: 16px;
  margin: 4px 2px;
  cursor: pointer;
  border: none;
  border-radius: 4px;
  transition: background-color 0.3s;
}

button:hover {
  background-color: #45a049;
}

.auth-button {
  background-color: #4CAF50;
}

.add-user-button {
  background-color: #2196F3;
  margin-left: 10px;
}

.add-user-button:hover {
  background-color: #0b7dda;
}

.status {
  margin: 20px 0;
  padding: 10px;
  border-radius: 4px;
}

.success { 
  background-color: #d4edda; 
  color: #155724; 
}

.error { 
  background-color: #f8d7da; 
  color: #721c24; 
}

.info { 
  background-color: #d1ecf1; 
  color: #0c5460; 
}
</style>