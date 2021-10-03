from PIL import Image
import numpy as np
import matplotlib.pyplot as plt
import os
import random
import math
import time
import tensorflow as tf
from tensorflow.keras import layers
from tensorflow import keras

def save_data():
    # LOAD IN DATA. Organize by patient, to prevent data leakage. 

    DIR = "AKOA_Analysis/"
    file_paths = [DIR + x for x in os.listdir(DIR)]
    new_patient_ids = {} # key: e.g. OAI9014797_BaseLine_3_L, value: new id
    data = {} # key: unique patient id (created), value: ([xdata], [labels [0 for left, 1 for right]])

    for file in file_paths:
        is_right = "RIGHT" in file
        patient_id = file.split("de3d1")[0].split("/")[1] + ("L" if not is_right else "R")
        if patient_id not in new_patient_ids:
            new_patient_ids[patient_id] = len(new_patient_ids)
        new_id = new_patient_ids[patient_id]
        img = np.asarray(Image.open(file).convert("L"))
        img = (img - np.amin(img)) / (np.amax(img) - np.amin(img))
        label = 1 if is_right else 0
        if new_id in data:
            data[new_id][0].append(img)
            data[new_id][1].append(label)
        else:
            data[new_id] = ([img], [label])


    # SPLIT DATA. Get train/test split based on patients. 

    TEST_SPLIT = 0.4
    num_patients = len(list(data.keys()))
    patient_ids = list(range(0, num_patients))
    test_patients = random.sample(patient_ids, int(num_patients*TEST_SPLIT))
    train_patients = [x for x in patient_ids if x not in test_patients]

    xtrain, xtest, ytrain, ytest = [], [], [], []
    for pid in patient_ids:
        #print(data[pid])
        for idx in range(len(data[pid][0])):
            if pid in train_patients:
                xtrain.append(data[pid][0][idx])
                ytrain.append(data[pid][1][idx])
            else:
                xtest.append(data[pid][0][idx])
                ytest.append(data[pid][1][idx])
    print(len(xtrain), len(xtest), len(ytrain), len(ytest))
    del data


    # SHUFFLE DATA AND SAVE. 

    indices_train = list(range(0, len(xtrain)))
    indices_test = list(range(0, len(xtest)))
    random.shuffle(indices_train)
    random.shuffle(indices_test)
    xtrain = np.array(xtrain)
    xtrain = xtrain[indices_train]
    np.save("xtrain", xtrain)
    #del xtrain
    xtest = np.array(xtest)
    xtest = xtest[indices_test]
    np.save("xtest", xtest)
    #del xtest
    ytrain = np.array(ytrain)
    ytrain = ytrain[indices_train]
    np.save("ytrain", ytrain)
    #del ytrain
    ytest = np.array(ytest)
    ytest = ytest[indices_test]
    np.save("ytest", ytest)
    #del ytest


SAVE_DATA = False

if SAVE_DATA:
    save_data()
else:
    #xtrain = np.load(r"C:\Users\hmunn\OneDrive\Desktop\COMP3710\Project\Data\xtrain.npy")
    xtest = np.load(r"C:\Users\hmunn\OneDrive\Desktop\COMP3710\Project\Data\xtest.npy")
    #ytrain = np.load(r"C:\Users\hmunn\OneDrive\Desktop\COMP3710\Project\Data\ytrain.npy")
    #ytest = np.load(r"C:\Users\hmunn\OneDrive\Desktop\COMP3710\Project\Data\ytest.npy")


# GET FOURIER FEATURES FOR POSITIONAL ENCODINGS. 

# img_data: tensor of shape (datapoints, rows, cols)
def get_positional_encodings(img_data, bands=4, sampling_rate=10):
    # assume 2 dimensions, using single channel images
    data_points, rows, cols = img_data.shape
    xr, xc = tf.linspace(-1,1,rows), tf.linspace(-1,1,cols)
    xd = tf.reshape(tf.stack(tf.reverse(tf.meshgrid(xr,xc), axis=[-3]),axis=2),(rows,cols,2))
    xd = tf.repeat(tf.expand_dims(xd, -1), repeats=[2*bands + 1], axis=3) # (rows, cols, 2, 2F + 1)
    # logscale for frequencies ( * pi) , 0 start as 10**0 = 1
    frequencies = tf.experimental.numpy.logspace(0.0,(tf.math.log(sampling_rate/2)/tf.math.log(10.)).numpy(), num = bands, dtype = tf.float32) * math.pi
    # (228,260,2,9)
    f_features = xd * tf.cast(tf.reshape(tf.concat([tf.math.sin(frequencies), tf.math.cos(frequencies), tf.constant([1.])], axis=0), (1,1,1,2*bands+1)), dtype=tf.double)
    f_features = tf.repeat(tf.reshape(f_features, (1,rows,cols,2*(2*bands + 1))), repeats=[data_points],axis=0) # (data_points, 228, 260, 18)
    return tf.reshape(tf.concat((img_data,f_features),axis=-1), (data_points, rows*cols, -1)) # add data in and flatten images

# DEFINE MODELS & HYPERPARAMETERS

latent_size = 512
data_size = 228*260
bands = 4
channel_size = 2*(2*bands + 1) + 1 # data (1) + 2 dim * (2F + 1)
transformer_heads = 4

def get_attention_module():
    data_input = layers.Input((data_size, channel_size))
    latent_input = layers.Input((latent_size, channel_size))

    # Q, K & V linear networks
    query_mlp = latent_input
    query_mlp = layers.LayerNormalization()(query_mlp)
    latent_output = query_mlp
    query_mlp = layers.Dense(channel_size)(query_mlp)

    key_mlp = data_input
    key_mlp = layers.LayerNormalization()(key_mlp)
    key_mlp = layers.Dense(channel_size)(key_mlp)

    value_mlp = data_input
    value_mlp = layers.LayerNormalization()(value_mlp)
    value_mlp = layers.Dense(channel_size)(value_mlp)

    # QKV cross-attention
    attention_module = layers.Attention(use_scale=True)([query_mlp, key_mlp, value_mlp])
    attention_module = layers.Dense(channel_size)(attention_module)
    attention_module = layers.Add()([latent_output, attention_module])
    attention_module = layers.LayerNormalization()(attention_module)

    # New query from attention module 
    new_latent = layers.Dense(channel_size, activation=tf.nn.gelu)(attention_module)
    new_latent = layers.Dense(channel_size, activation=tf.nn.gelu)(new_latent)
    new_latent = layers.Dense()(new_latent)
    new_latent = layers.Add()([attention_module, new_latent])

    cross_attention = keras.Model(inputs=[data_input, latent_input], outputs = new_latent)
    return cross_attention

def get_transformer_module():
    latent_input = layers.Input((latent_size, channel_size))
    layer_init = latent_input
    for i in range(6): # 6 transformer blocks
        transformer = layers.LayerNormalization()(layer_init)
        transformer = layers.MultiHeadAttention(num_heads = transformer_heads, key_dim = channel_size)(transformer, transformer, \
            return_attention_scores = False)
        transformer = layers.Add()([latent_input, transformer])
        transformer = layers.LayerNormalization()(transformer)
        
        new_query = layers.Dense(channel_size, activation=tf.nn.gelu)(transformer)
        new_query = layers.Dense(channel_size, activation=tf.nn.gelu)(new_query)
        new_query = layers.Dense()(new_query)
        transformer = layers.Add()([new_query, transformer])
        layer_init = transformer

    return keras.Model(inputs = latent_input, outputs = transformer)

def get_classifier_module(final_latent):
    classifier = layers.GlobalAveragePooling1D()(final_latent)
    classifier = layers.Dense(1, activation='sigmoid')(classifier) # binary crossentropy
    return classifier

''' TODO:
    2. Training code
    3. Tuning (dropout, data augmentation etc.)
    4. Plots, accuracy
'''