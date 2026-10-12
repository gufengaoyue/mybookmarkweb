const express = require('express');
const fs = require('fs');
const path = require('path');
const cors = require('cors');
const bodyParser = require('body-parser');

const app = express();
const DATA_FILE = path.join(__dirname, '/api/links.json');

// 中间件配置
app.use(cors());
app.use(bodyParser.json());

// 确保数据文件存在
if (!fs.existsSync(DATA_FILE)) {
  fs.writeFileSync(DATA_FILE, '[]');
}

// 读取数据
function readData() {
  return JSON.parse(fs.readFileSync(DATA_FILE));
}

// 写入数据
function saveData(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

function validateItem(item) {
    try {
        new URL(item.url); // 使用URL对象验证
        return !!item.name?.trim();
    } catch {
        return false;
    }
}

// API端点
app.get('/api/links', (req, res) => {
  try {
    const data = readData();
    res.json(data);
  } catch (error) {
    res.status(500).send('读取数据失败');
  }
});

app.post('/api/links', (req, res) => {
  const newItem = {
    name: req.body.name?.trim(),
    url: req.body.url,
    icon: req.body.icon || null,
    id: req.body.id || Date.now()
  };

  // 验证数据（[[10]](#__10) [[15]](#__15)）
if (!newItem.name || !newItem.url || !/^https?:\/\/[^\s/$.?#].[^\s]*$/.test(newItem.url)) {
  return res.status(400).send('无效数据：名称不能为空且URL必须是有效的格式');
}


  try {
    const data = readData();
    data.push(newItem);
    saveData(data);
    res.status(201).json(newItem);
  } catch (error) {
    res.status(500).send('保存失败');
  }
});

// 更新链接（PUT /api/links/:id）
app.put('/api/links/:id', (req, res) => {
  try {
    const id = req.params.id;
    const updatedItem = req.body;
//    console.log(updatedItem);

    // 数据验证（复用添加逻辑）
    if (!validateItem(updatedItem)) {
      return res.status(400).send('无效数据');
    }

    const data = readData();
    const index = data.findIndex(item => item.id.toString() === id.toString());

//    console.log(index);

    if (index === -1) {
      return res.status(404).send('条目不存在');
    }

   data[index] = { ...data[index], ...updatedItem };
//   console.log(data[index]);

    saveData(data);
    res.json(data[index]);
//    console.log(data);
  } catch (error) {
    res.status(500).send('更新失败');
  }
});

// 删除链接（DELETE /api/links/:id）
app.delete('/api/links/:id', (req, res) => {
  try {
    const id = req.params.id;
    const data = readData().filter(item => item.id.toString() !== id.toString());

    if (data.length === readData().length) {
      return res.status(404).send('条目不存在');
    }

    saveData(data);
    res.status(204).send();
  } catch (error) {
    res.status(500).send('删除失败');
  }
});

// server.js 新增路由
app.get('/api/links/:id', (req, res) => {
  try {
    const id = req.params.id;
    const data = readData();
    const item = data.find(i => i.id.toString() === id.toString());

    if (!item) {
      return res.status(404).json({ error: "条目不存在" });
    }

    res.json(item);
  } catch (error) {
    res.status(500).json({
      error: "服务器内部错误",
      detail: error.message
    });
  }
});

// 新增顺序更新接口
app.post('/api/links/order', (req, res) => {
  try {
    const newOrder = req.body.nod;
    const data = readData();

    // 根据ID顺序重新排列数据
    const orderedData = newOrder.map(id =>
      data.find(item => item.id.toString() === id)
    ).filter(Boolean);

    fs.writeFileSync(DATA_FILE, JSON.stringify(orderedData, null, 2));
    res.sendStatus(200);
  } catch (error) {
    console.error('顺序更新失败:', error);
    res.status(500).send('顺序更新失败');
  }
});


app.listen(3000, () => console.log('服务运行在 http://localhost:3000'));
