    // 表单提交处理

let server = 'http://localhost:3000/api/links';

function handleSubmit(e) {
  e.preventDefault();

  const newItem = {
    name: document.getElementById('name').value.trim(),
    url: document.getElementById('url').value,
    icon: document.getElementById('icon').value.trim() || null,
    id: Date.now()
  };

  if (!validateItem(newItem)) {
    alert('请输入有效的名称和URL');
    return false;
  }

  addLink(newItem);
  // 清空表单
  document.getElementById('addForm').reset();
  return false;
}

async function loadData() {
    try {
      const response = await fetch(server);
      const data = await response.json();
//      data = updateIconCache(data); // 更新图标缓存
      renderCards(data);
      initDragAndDrop(); // 初始化拖拽
      const searchInput = document.getElementById('search-input');
      searchInput.focus();

    } catch (error) {
      console.error('加载失败:', error);
    };
  }

function validateItem(item) {
    try {
        var url = new URL(item.url); // 使用URL对象验证
       return !!item.name?.trim();
//        return item && item.name ? item.name.trim() : '';
        // return true;
    } catch {
        return false;
    }
}

function renderCards(items) {
    const container = document.getElementById('cards');
    container.innerHTML = items.map(item => `
            <div class="card" data-id="${item.id}" draggable="true">
                <a href="${item.url}" >
                    <img src="${item.icon}" class="card-icon" onerror="this.style.display='none'" onload="this.style.display='block'">
                </a>
                <a href="${item.url}" target="_blank">
                    <div class="card-content">
                            <h3 class="card-title">${item.name}</h3>
                    </div>
                </a>
                <div class="action-buttons">
                    <button class="edit-btn" onclick="editLink(${item.id})">✏️</button>
                    <button class="delete-btn" onclick="deleteLink(${item.id})">🗑️</button>
                </div>
       </div>
    `).join('');
}

function initDragAndDrop() {
  let draggedCard = null;
  let originalIndex = 0;

  document.querySelectorAll('.card').forEach(card => {
    card.draggable = true;

    // 拖拽开始
    card.addEventListener('dragstart', e => {
      draggedCard = card;
      originalIndex = Array.from(card.parentNode.children).indexOf(card);
      card.classList.add('dragging');
      e.dataTransfer.setData('text/plain', card.dataset.id);
    });

    // 拖拽结束
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      saveNewOrder();
    });

    // 拖拽经过
    card.addEventListener('dragover', e => {
      e.preventDefault();
      if (draggedCard === card) return;

      const rect = card.getBoundingClientRect();
      const midX = rect.left + rect.width / 2;

      if (e.clientX < midX) {
        card.classList.add('slide-left');
        card.parentNode.insertBefore(draggedCard, card);
      } else {
        card.classList.add('slide-right');
        card.parentNode.insertBefore(draggedCard, card.nextSibling);
      }
    });

    // 动画结束清理
    card.addEventListener('animationend', () => {
      card.classList.remove('slide-left', 'slide-right');
    });
  });

  // 保存新顺序到服务器
  async function saveNewOrder() {
    const cardIds = Array.from(document.querySelectorAll('.card'))
                      .map(card => card.dataset.id);

    try {
      const response = await fetch(server + '/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nod: cardIds })
      });

      if (!response.ok) throw new Error('保存失败');
      loadData(); // 刷新数据确保一致性
    } catch (error) {
      console.error('保存顺序失败:', error);
      alert('顺序保存失败，请重试');
    }
  }
}

// 修正后的表单功能
function initForm() {
    document.getElementById('addForm').addEventListener('submit', e => {
        e.preventDefault();
        const newItem = {
            name: e.target.name.value.trim(),
            url: e.target.url.value,
            icon: e.target.icon.value.trim() || null
        };

        if (!validateItem(newItem)) {
            alert('请输入有效的名称和URL');
            return;
        }

        data.push(newItem);
        renderCards(data);
        saveToLocal(newItem);
        e.target.reset();
    });
}

async function addLink(newItem) {
try {
  const response = await fetch(server, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(newItem)
  });

  if (!response.ok) throw new Error('保存失败');
  loadData(); // 刷新数据
} catch (error) {
  alert(error.message);
}
}

async function deleteLink(id) {
  if (!confirm('确认删除此链接？')) return;

  try {
    const response = await fetch(server + '/' + id.toString(), {
      method: 'DELETE'
    });

    if (!response.ok) throw new Error('删除失败');
    loadData(); // 刷新列表
  } catch (error) {
    alert(error.message);
  }
}

// 使用百度搜索关键字，并打开新标签页
function handleSearch(e) {
    const keyword = document.getElementById('search-input').value.trim();
    if (!keyword) return;
    // 根据搜索引擎不同，使用不同的搜索语法
    const engine = document.getElementById('search-engine').value;
    let url = '';
    switch (engine) {
        case 'google':
            url = `https://www.google.com/search?q=${keyword}`;
            break;
        case 'bing':
            url = `https://www.bing.com/search?q=${keyword}`;
            break;
        case 'baidu':
            url = `https://www.baidu.com/s?wd=${keyword}`;
            break;
        case '360':
            url = `https://www.so.com/s?q=${keyword}`;
            break;
        default:
            url = `https://www.baidu.com/s?wd=${keyword}`;
            break;
    }
    window.open(url, '_blank');
    document.getElementById('search-input').value = '';
}


async function editLink(id) {
  // 获取原始数据
  const server_id = server + '/' + id.toString();
  const original = await fetch(server_id).then(r => r.json());

  const modal = document.getElementById("collectModal");
  modal.style.display = "block";

  const form = document.getElementById('collectForm');
  const textName = document.getElementById('collectName');
  const textUrl = document.getElementById('collectUrl');
  const textIcon = document.getElementById('collectIcon');
  const saveBtn = document.getElementById('saveBtn');
  textName.value = original.name;
  textUrl.value = original.url;
  textIcon.value = original.icon || '';
  
  // 修改表单提交逻辑
  saveBtn.onclick = async (e) => {
    e.preventDefault();
    const updatedItem = {
      name: textName.value,
      url: textUrl.value,
      icon: textIcon.value,
      id: original.id
    };
    try {
      const response = await fetch(server_id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedItem)
      });

      if (!response.ok) throw new Error('更新失败!');
      loadData(); // 刷新列表
      textIcon.value = '';
      textName.value = '';
      textUrl.value = '';
      modal.style.display = "none";
      saveBtn.onclick = handleSubmitForFav;
    } catch (error) {
      alert(error.message);
    }
  };

  setTimeout(() => {textName.focus(); }, 300);
  
}

async function handleSubmitForFav(e) {
      e.preventDefault();
      const newItem = {
        name: document.getElementById('collectName').value.trim(),
        url: document.getElementById('collectUrl').value.trim(),
        icon: document.getElementById('collectIcon').value.trim() || null,
        id: Date.now()
      };

      if(!newItem.name || !newItem.url) {
        alert('名称和网址为必填项');
        return false;
      }
    addLink(newItem);
      clearForm();
      return false;
}

function clearForm(){
      document.getElementById('collectName').value = '';
       document.getElementById('collectUrl').value = '';
       document.getElementById('collectIcon').value = '';
       document.getElementById("collectModal").style.display = "none";
}

function toggleModal(action) {
  const modal = document.getElementById("collectModal");
  modal.style.display = action;
}

// 按下ESC关闭弹窗
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' || e.code === 'Escape') {    
    clearForm();
  }
});

// 点击弹窗外部关闭弹窗
window.onclick = (e) =>
 {
 const modal = document.getElementById("collectModal");
  if (e.target == modal) {
    clearForm();
  }
}
