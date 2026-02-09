# vk_publisher.py
import vk_api
import os
from config import Config

class VKPublisher:
    def __init__(self):
        self.token = Config.VK_ACCESS_TOKEN
        self.group_id = Config.VK_GROUP_ID
        
        try:
            self.vk_session = vk_api.VkApi(token=self.token)
            self.vk = self.vk_session.get_api()
            self.enabled = True
            print("✅ VK подключен")
        except Exception as e:
            print(f"❌ Ошибка подключения VK: {e}")
            self.enabled = False
    
    def publish_article(self, article_text, image_path=None):
        """Публикует статью в VK"""
        if not self.enabled:
            print("❌ VK не подключен")
            return None
        
        try:
            attachments = []
            
            # Загружаем картинку если есть
            if image_path and os.path.exists(image_path):
                try:
                    upload = vk_api.VkUpload(self.vk_session)
                    photo = upload.photo_wall(image_path, group_id=abs(int(self.group_id)))
                    photo_id = f"photo{photo[0]['owner_id']}_{photo[0]['id']}"
                    attachments.append(photo_id)
                    print("✅ Изображение загружено в VK")
                except Exception as e:
                    print(f"⚠️ Не удалось загрузить изображение: {e}")
            
            # Публикуем пост
            result = self.vk.wall.post(
                owner_id=self.group_id,
                message=article_text,
                attachments=','.join(attachments) if attachments else None,
                from_group=1,
                copyright="https://snoomi.ru"
            )
            
            post_id = result['post_id']
            print(f"✅ Пост опубликован! ID: {post_id}")
            return post_id
            
        except Exception as e:
            print(f"❌ Ошибка публикации: {e}")
            return None