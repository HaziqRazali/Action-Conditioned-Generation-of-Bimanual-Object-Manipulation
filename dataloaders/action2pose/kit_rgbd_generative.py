import os
import re
import sys
import ast
import copy
import json
import time
import math
import torch 
import random
import numpy as np

from glob import glob
from scipy import interpolate
from natsort import natsorted
from collections import Counter, OrderedDict
   
sys.path.append(os.path.join(os.path.expanduser("~"),"Action-Conditioned-Generation-of-Bimanual-Object-Manipulation","dataloaders"))
from utils import *
import kit_rgbd_variables as var

class dataloader(torch.utils.data.Dataset):
    def __init__(self, args, dtype):
    
        assert dtype == "train" or dtype == "val"    
        for key, value in args.__dict__.items():
            setattr(self, key, value)
        self.dtype = dtype
        
        # action        
        self.clf_actions = self.fine_actions
        setattr(args, "clf_actions", self.clf_actions)
        self.main_action_to_id = {a:i for i,a in enumerate(self.main_actions)}
        self.fine_action_to_id = {a:i for i,a in enumerate(self.fine_actions)}
        
        # list of all objects
        self.all_objects = var.all_objects
        
        # action -> objects
        self.action_to_objects = var.action_to_objects
                
        # get the list of present objects given the main actions
        action_to_objects = []
        for main_action in self.main_actions:
            action_to_objects.extend(self.action_to_objects[main_action])
        # remove duplicates
        action_to_objects = list(set(action_to_objects))
        action_to_objects = sorted(action_to_objects)   
        # get ID
        self.object_name_to_id = {k:i+1 for i,k in enumerate(action_to_objects)}
        self.object_id_to_name = {i+1:k for i,k in enumerate(action_to_objects)}
        for i,action_to_object in enumerate(action_to_objects):
            print(i+1, action_to_object)
        print()
        self.num_obj_classes = len(action_to_objects) + 1 - 2
        self.num_obj_wrist_classes = self.num_obj_classes + 2
        setattr(args, "num_obj_wrist_classes", self.num_obj_wrist_classes)
        setattr(args, "obj_wrist_padded_length", self.object_padded_length+2)
        
        # # # # # # # 
        # load data #
        # # # # # # #
                
        data = []        
        folders = os.path.join(self.data_root,self.data_name,"*")
        folders = glob(folders)
        if len(folders) == 0:
            print("No data found at:", os.path.join(self.data_root,self.data_name,"*"))
            sys.exit()
        folders = natsorted(folders)
        for folder in folders:
            files = glob(os.path.join(folder,"*"))
            files = natsorted(files)
            for file in files:
                print(file)
                sequence_data = json.load(open(file,"r"))
                
                #for key in sequence_data.keys():
                #    print(key)
                #sys.exit()
                
                # convert to array
                for k,v in sequence_data.items():
                    if "obj_names" not in k and type(v) == type(list([])):
                        sequence_data[k] = np.array(v)
                
                # filename
                sequence = sequence_data["sequence"]
        
                # frames
                inp_frame = sequence_data["inp_frame"]
        
                # # # # # # # #
                # object data #
                # - no table  #
                # # # # # # # #
                
                # object names
                obj_names = ast.literal_eval(sequence_data["obj_names"]) if "obj_names" in sequence_data.keys() else None
                obj_names = [x.split("_")[0] for x in obj_names]
                
                # object xyz
                pred_obj_xyz = np.transpose(sequence_data["pred_obj_xyz"], (1,0,2,3)) # [n-1, len, 4, 3]
                true_obj_xyz = np.transpose(sequence_data["true_obj_xyz"], (1,0,2,3)) # [n-1, len, 4, 3]
                obj_xyz_unpadded_length = sequence_data["obj_xyz_unpadded_length"]
                
                """ sanity check
                # use velocities to suppress irrelevant objects to 0
                # irrelevant objects will have a velocity of 0
                if "true_obj_xyz_vel" in sequence_data.keys():
                    true_obj_xyz_vel = np.transpose(sequence_data["true_obj_xyz_vel"], (1,0,2,3)) # [n-1, len, 4, 3]
                else:
                    true_obj_xyz_vel = np.transpose(sequence_data["obj_xyz_vel"], (1,0,2,3)) # [n-1, len, 4, 3]  
                #print("obj_names",obj_names)
                #print("unused objects")
                if self.add_distractors == 0:
                    for i in range(true_obj_xyz_vel.shape[0]):
                        if np.sum(np.abs(true_obj_xyz_vel[i])) == 0:
                            pred_obj_xyz[i,:] = true_obj_xyz[i,0]
                        #print(pred_obj_xyz[i,:].shape)
                        #print(obj_names[i])
                #print()
                """
                
                # # # # # # # #
                # wrist data  #
                # # # # # # # #
                
                hand_names = ast.literal_eval(sequence_data["hand_names"])
                pred_wrist_xyz = sequence_data["pred_wrist_xyz"]                      # [len, 10, 3]
                true_wrist_xyz = sequence_data["true_wrist_xyz"]                      # [len, 10, 3]
                wrist_xyz_unpadded_length = sequence_data["wrist_xyz_unpadded_length"]
                if pred_wrist_xyz.shape != true_wrist_xyz.shape:
                    pred_wrist_xyz = true_wrist_xyz
                    print("Assigning true_wrist_xyz to pred_wrist_xyz! Should only happen for full-body!")
                                                  
                # # # # # # # 
                # pose data #
                # # # # # # #
                
                # for the rnn baseline that uses the full body
                if "pred_xyz" in sequence_data.keys():
                    pred_xyz = sequence_data["pred_xyz"]
                else:
                    pred_xyz = sequence_data["true_xyz"]
                xyz_unpadded_length = sequence_data["xyz_unpadded_length"]
                
                # # # # # # # #
                # action data #
                # # # # # # # #
                
                lhand_action_ids = sequence_data["lhand_action_ids"]
                rhand_action_ids = sequence_data["rhand_action_ids"]
                
                lhand_action_ohs = sequence_data["lhand_action_ohs"]
                rhand_action_ohs = sequence_data["rhand_action_ohs"]
                rhand_main_action = sequence_data["rhand_main_action"]
                
                # # # # # #
                # append  #
                # # # # # #
                
                             # metadata
                data.append({"sequence":sequence, "inp_frame":inp_frame,
                
                             # action data
                             "lhand_action_ids":lhand_action_ids, "rhand_action_ids":rhand_action_ids,
                             "lhand_action_ohs":lhand_action_ohs, "rhand_action_ohs":rhand_action_ohs,
                             "rhand_main_action":rhand_main_action,
                
                             # object data
                             "obj_names":obj_names, "pred_obj_xyz":pred_obj_xyz, "true_obj_xyz":true_obj_xyz, "obj_xyz_unpadded_length":obj_xyz_unpadded_length,
                                             
                             # hand data
                             "hand_names":hand_names,
                             "pred_wrist_xyz":pred_wrist_xyz, "wrist_xyz_unpadded_length":wrist_xyz_unpadded_length,
                             "pred_xyz":pred_xyz,
                             "xyz_unpadded_length":xyz_unpadded_length
                             })
        
        self.data_len = len(data)
        self.data = data
        
    def __len__(self):
        
        # 54 or 32
        return max(len(self.data),self.batch_size)
    
    def __getitem__(self, idx):

        # resample a random value if the sampled idx goes beyond data_len. This ensures that it does not matter how I augment the data
        if idx > self.data_len:
            idx = random.randint(0,self.__len__())
            
        # get the data
        sequence_data = self.data[idx]
                
        # sequence name
        sequence = sequence_data["sequence"]
        
        # frame
        inp_frame = sequence_data["inp_frame"]
                
        # # # # # # # #
        # object data #
        # - no table  #
        # # # # # # # #
        
        # name, id, oh
        obj_names = sequence_data["obj_names"]
        obj_ids   = np.array([self.object_name_to_id[x] for x in obj_names])
        obj_ids_padded = pad(obj_ids,self.object_padded_length).astype(int)
        obj_ohs_padded = one_hot(obj_ids_padded,self.num_obj_wrist_classes)
        
        # - no need to scale
        # - no need to center
        # - verify numbers with true / etc in process_obj
        pred_obj_xyz = sequence_data["pred_obj_xyz"]                                                # [n, t*time_step_size, num_markers, 3]
        pred_obj_xyz = pred_obj_xyz[:,::int(self.time_step_size)]                                   # [n, t,                num_markers, 3]
        pred_obj_xyz_padded = np.stack([pad(x, self.pose_padded_length) for x in pred_obj_xyz])     # [n, padded t, num_markers, 3]
        pred_obj_xyz_padded = pad(pred_obj_xyz_padded, self.object_padded_length)                   # [padded n, padded t, num_markers, 3]
        pred_obj_xyz_padded = np.transpose(pred_obj_xyz_padded,[1,0,2,3])                           # [padded t, padded n, num_markers, 3]
        #pred_obj_xyz_unpadded_length = pred_obj_xyz.shape[1]
                
        true_obj_xyz = sequence_data["true_obj_xyz"]                                                # [n, t*time_step_size, num_markers, 3]
        true_obj_xyz = true_obj_xyz[:,::int(self.time_step_size)]                                   # [n, t,                num_markers, 3]
        true_obj_xyz_padded = np.stack([pad(x, self.pose_padded_length) for x in true_obj_xyz])     # [n, padded t, num_markers, 3]
        true_obj_xyz_padded = pad(true_obj_xyz_padded, self.object_padded_length)                   # [padded n, padded t, num_markers, 3]
        true_obj_xyz_padded = np.transpose(true_obj_xyz_padded,[1,0,2,3])                           # [padded t, padded n, num_markers, 3]
        #true_obj_xyz_unpadded_length = true_obj_xyz.shape[1]
        
        obj_xyz_unpadded_length = pred_obj_xyz.shape[1] #int(sequence_data["obj_xyz_unpadded_length"]/self.time_step_size)
        
        # # # # # # # #
        # wrist data  #
        # # # # # # # #
        
        pred_wrist_xyz = sequence_data["pred_wrist_xyz"]                        # [t*time_step_size, 10, 3]
        pred_wrist_xyz = pred_wrist_xyz[::int(self.time_step_size)]             # [t,                10, 3]
        pred_wrist_xyz_padded = pad(pred_wrist_xyz, self.pose_padded_length)    # [padded t, 10, 3]
        wrist_xyz_unpadded_length = pred_wrist_xyz.shape[0]
                
        hand_names = sequence_data["hand_names"]
        hand_ids   = np.array([self.object_name_to_id[hand_name.split("_")[0]] for hand_name in hand_names])
        hand_ohs   = one_hot(hand_ids,self.num_obj_wrist_classes)

        # # # # # # #
        # pose data #
        # # # # # # #
        
        pred_xyz = sequence_data["pred_xyz"]                        # [t*time_step_size, 15, 2]
        pred_xyz = pred_xyz[::int(self.time_step_size)]             # [t,                15, 2]
        pred_xyz_padded = pad(pred_xyz, self.pose_padded_length)    # [padded t,         15, 2]
        xyz_unpadded_length = pred_xyz.shape[0]
        
        """print(sequence)
        print(obj_xyz_unpadded_length)
        print(pred_obj_xyz_padded.shape)
        print(pred_wrist_xyz.shape)
        for i in range(obj_xyz_unpadded_length):
            print(i)
            print()
            print(pred_obj_xyz_padded[:,i])
            print()
            print(pred_wrist_xyz[i])
            input()
        sys.exit()"""
        
        # # # # # # # #
        # action data #
        # # # # # # # #
        
        lhand_action_ids = sequence_data["lhand_action_ids"]
        lhand_action_ids_padded, lhand_action_ids_unpadded_length = self.sample_and_pad(lhand_action_ids)
        rhand_action_ids = sequence_data["rhand_action_ids"]
        rhand_action_ids_padded, rhand_action_ids_unpadded_length = self.sample_and_pad(rhand_action_ids)
        
        lhand_action_ohs = sequence_data["lhand_action_ohs"]
        lhand_action_ohs_padded, lhand_action_ohs_unpadded_length = self.sample_and_pad(lhand_action_ohs)
        rhand_action_ohs = sequence_data["rhand_action_ohs"]
        rhand_action_ohs_padded, rhand_action_ohs_unpadded_length = self.sample_and_pad(rhand_action_ohs)
        
        rhand_main_action = sequence_data["rhand_main_action"]
        
        return_data = {# metadata
                       "sequence":sequence, "inp_frame":inp_frame,
                               
                       # pose data
                       "xyz":pred_xyz_padded, "xyz_unpadded_length":obj_xyz_unpadded_length,
                       
                       # object data
                       "obj_ids":obj_ids_padded, "obj_ohs":obj_ohs_padded, 
                       "obj_xyz":pred_obj_xyz_padded, "obj_xyz_unpadded_length":obj_xyz_unpadded_length,
        
                       # wrist data
                       "wrist_ohs":hand_ohs, "wrist_xyz":pred_wrist_xyz_padded, "wrist_xyz_unpadded_length":wrist_xyz_unpadded_length,
                       
                       # action data
                       "lhand_action_ids":lhand_action_ids_padded, "lhand_action_ids_unpadded_length":lhand_action_ids_unpadded_length,
                       "rhand_action_ids":rhand_action_ids_padded, "rhand_action_ids_unpadded_length":rhand_action_ids_unpadded_length,
                       "lhand_action_ohs":lhand_action_ohs_padded, "lhand_action_ohs_unpadded_length":lhand_action_ohs_unpadded_length,
                       "rhand_action_ohs":rhand_action_ohs_padded, "rhand_action_ohs_unpadded_length":rhand_action_ohs_unpadded_length,
                       "rhand_main_action":rhand_main_action
                       }

        # don't have to load distractor because the model would have output it
        # still have to flip
        return_data = self.flip_data(return_data)
        
        # convert all list of strings into a single string
        for k,v in return_data.items():
            if type(v) == type([]) and type(v[0]) == type("string"):
                return_data[k] = str(v)
                
        # convert all array type to float32
        for k,v in return_data.items():
            if type(v) == type(np.array(1)):
                return_data[k] = return_data[k].astype(np.float32)
        """
        for k,v in return_data.items():
            if type(v) == type(np.array([1])):
                print(k, v.shape)
        print()
        """
        
        #print(return_data["wrist_xyz"].shape)
        #print(return_data["reversed_wrist_xyz"].shape)
        
        return return_data

    def flip_data(self, data):
        
        # get data
        obj_xyz,   obj_xyz_unpadded_length   = data["obj_xyz"],   data["obj_xyz_unpadded_length"]   # [padded t, padded n, num_markers, 3]
        wrist_xyz, wrist_xyz_unpadded_length = data["wrist_xyz"], data["wrist_xyz_unpadded_length"] # [padded t, 10, 3]
                        
        # unpad
        reversed_obj_xyz    = obj_xyz[:obj_xyz_unpadded_length]
        reversed_wrist_xyz  = wrist_xyz[:wrist_xyz_unpadded_length]
        
        # flip
        reversed_obj_xyz    = reversed_obj_xyz[::-1]
        reversed_wrist_xyz  = reversed_wrist_xyz[::-1]
        
        # pad
        reversed_obj_xyz = pad(reversed_obj_xyz, self.pose_padded_length) # pad(reversed_obj_xyz,self.pose_padded_length)
        reversed_wrist_xyz = pad(reversed_wrist_xyz,self.pose_padded_length)
        
        data["reversed_obj_xyz"] = reversed_obj_xyz
        data["reversed_wrist_xyz"] = reversed_wrist_xyz
        
        return data
        
    def sample_and_pad(self, data):
        
        data = data[::int(self.time_step_size)]
        data_padded = pad(data, self.pose_padded_length)
        return data_padded, data.shape[0]