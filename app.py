# 导入我们需要的工具
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime

# --- 应用和数据库配置 (不变) ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-key-that-you-should-change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# --- 数据库模型定义 (增加了 Remark 模型) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    posts = db.relationship('Post', backref='author', lazy=True)
    remarks = db.relationship('Remark', backref='author', lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    remarks = db.relationship('Remark', backref='post', lazy=True, cascade="all, delete-orphan")

# 【新模型】定义 Remark 模型
class Remark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    highlighted_text = db.Column(db.Text, nullable=False)
    remark_text = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)


# --- 路由定义 ---
# 【请用这个新版本替换旧的 home 函数】
@app.route('/')
def home():
    all_posts = Post.query.order_by(Post.timestamp.desc()).all()
    all_remarks = Remark.query.all()

    # 【关键修复在这里！】
    remarks_by_post = {}
    for remark in all_remarks:
        if remark.post_id not in remarks_by_post:
            remarks_by_post[remark.post_id] = []

        # 我们不再直接传递 Remark 对象，而是把它转换成一个简单的字典
        remarks_by_post[remark.post_id].append({
            'highlighted_text': remark.highlighted_text,
            'remark_text': remark.remark_text,
            'author_username': remark.author.username # 直接传递用户名字符串
        })

    user = User.query.get(session.get('user_id'))
    return render_template('home.html', user=user, posts=all_posts, remarks_by_post=remarks_by_post)
# 【新功能】添加备注的 API 路由
@app.route('/add_remark', methods=['POST'])
def add_remark():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401

    data = request.get_json()
    post_id = data.get('post_id')
    highlighted_text = data.get('highlighted_text')
    remark_text = data.get('remark_text')

    if not all([post_id, highlighted_text, remark_text]):
        return jsonify({'success': False, 'message': '数据不完整'}), 400

    new_remark = Remark(
        post_id=post_id,
        user_id=session['user_id'],
        highlighted_text=highlighted_text,
        remark_text=remark_text
    )
    db.session.add(new_remark)
    db.session.commit()

    return jsonify({
        'success': True, 
        'message': '备注已保存',
        'remark': {
            'id': new_remark.id,
            'remark_text': new_remark.remark_text,
            'author': new_remark.author.username
        }
    })

# --- 其他路由 (保持不变，为了简洁省略) ---
@app.route('/create', methods=['GET', 'POST'])
def create_post():
    if 'user_id' not in session:
        flash("请先登录后再发布内容。", "error"); return redirect(url_for('login'))
    if request.method == 'POST':
        post_content = request.form['content']
        if not post_content: flash("内容不能为空！", "error"); return redirect(url_for('create_post'))
        new_post = Post(content=post_content, user_id=session['user_id'])
        db.session.add(new_post); db.session.commit()
        flash("内容发布成功！", "success"); return redirect(url_for('home'))
    return render_template('create_post.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']; password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash("这个用户名已经被注册了！", "error"); return redirect(url_for('register'))
        new_user = User(username=username, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user); db.session.commit()
        session['user_id'] = new_user.id
        flash("注册成功并已自动登录！", "success"); return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']; password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash("登录成功！", "success"); return redirect(url_for('home'))
        else:
            flash("用户名或密码错误！", "error"); return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("你已成功注销。", "info"); return redirect(url_for('home'))

# 【新功能】删除帖子的路由
@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post():
    # 确保用户已登录
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # 从数据库中查找帖子
    post_to_delete = Post.query.get_or_404(post_id)

    # 【重要】检查当前登录的用户是否是帖子的作者
    if post_to_delete.author.id != session['user_id']:
        flash("你没有权限删除这篇内容！", "error")
        return redirect(url_for('home'))
    
    # 从数据库中删除帖子
    db.session.delete(post_to_delete)
    db.session.commit()
    
    flash("内容已成功删除。", "success")
    return redirect(url_for('home'))
# --- 启动应用 ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)