from keras.preprocessing.image import ImageDataGenerator, array_to_img, img_to_array, load_img
import numpy as np
import os

datagen = ImageDataGenerator(
                             rotation_range=180,
#                             horizontal_flip=True,
#                             vertical_flip=True,
                             fill_mode='wrap'    #"constant", "nearest", "reflect" or "wrap"
)

#arguments
dir = 'old_data/preview/'   #directory of image
img = 'out_11_28.png'       #original image
num_images = 5              #number of images to generate
save_prefix = 'rot_wrap'    #prefix of newly generated images

#load image
image = load_img('%s%s'%(dir,img))
x = img_to_array(image)         # this is a Numpy array with shape (3, 224, 224)
x = x.reshape((1,) + x.shape)   # this is a Numpy array with shape (1, 3, 224, 224)

#generate new transformed images with .flow()
i = 0
os.system('rm %s%s*'%(dir,save_prefix))     #delete previous images before making new ones
for batch in datagen.flow(x, batch_size=1,
                          save_to_dir='old_data/preview', save_prefix=save_prefix, save_format='jpeg'):
    i += 1
    if i > num_images - 1:
        break  # otherwise the generator would loop indefinitely
