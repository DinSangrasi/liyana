import os
import cv2
import json
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt

import sys

sys.path.append("../../")
from face_detection import mtcnn_detector
from age_sex_ethnicity_detection import final_predicter as ASE_FP
from deepfake_detection import final_predicter as DF_FP

from glob import glob
from shutil import rmtree
from sklearn.decomposition import PCA


class Utils:
	def __init__(self):
		os.makedirs("saved_outputs", exist_ok=True)
		os.makedirs("faces", exist_ok=True)

		os.makedirs("faces2display", exist_ok=True)
		rmtree("faces2display")
		os.makedirs("faces2display", exist_ok=True)

	@staticmethod
	def get_json_id():
		json_files = glob("saved_outputs/*.json")
		max_id = 0
		for file in json_files:
			max_id = max(max_id, int(os.path.split(file.rstrip(".json"))[-1]))

		return str(max_id + 1)

	@staticmethod
	def get_faces2display_id():
		json_files = glob("faces2display/*.jpg")
		max_id = 0
		for file in json_files:
			max_id = max(max_id, int(os.path.split(file.rstrip(".jpg"))[-1]))

		return str(max_id + 1)

	def save_outputs(self, path, outputs):
		file_id = self.get_json_id()
		file_path = os.path.join("saved_outputs/", file_id + ".json")
		file_dict = {"path": path, "outputs": outputs.tolist()}

		with open(file_path, 'w') as outfile:
			json.dump(file_dict, outfile)

		return file_id


class DataBaseManager:
	def save(self):
		with open(self.database_path, 'w') as outfile:
			json.dump(self.data, outfile)

	def get_new_id(self):
		all_ids = list(set(list(self.data.keys())))
		if len(all_ids) == 0:
			all_ids = [0]

		return int(all_ids[-1]) + 1

	def get_2d_space(self):
		try:
			outputs = []
			y_data = []
			for key in self.data:
				outputs.append(self.data[key]["output"])
				y_data.append(int(key))

			outputs = tf.convert_to_tensor(outputs).numpy().reshape(-1, 512)
			pc_all = self.pca.fit_transform(outputs)

			fig, ax = plt.subplots(figsize=(10, 10))
			fig.patch.set_facecolor('white')
			for l in np.unique(y_data)[:10]:
				ix = np.where(y_data == l)
				ax.scatter(pc_all[:, 0][ix], pc_all[:, 1][ix])

			plt.savefig("2d_space.jpg")
		except Exception as e:
			print(e)
			return bytes(np.array([-1], dtype=np.float32))

		return bytes(np.array([1], dtype=np.float32))

	def __init__(self, distance_metric):
		self.database_path = "database.json"
		self.distance_metric = distance_metric
		self.pca = PCA(n_components=2)  # compress 512-D data to 2-D, we need to do that if we want to display data.

		if not os.path.exists(self.database_path):
			q = open(self.database_path, "w+")
			q.write("{}")
			q.close()

		with open(self.database_path, "r") as read_file:
			self.data = json.load(read_file)

	def find_match_in_db(self, output, th: float = 1.2):
		min_im = (1.0, -1, "none")
		for key in self.data:
			output_db = tf.convert_to_tensor(self.data[key]["output"])
			dist = self.distance_metric(output_db, output).numpy()
			if dist < min_im[0]:
				min_im = (dist, int(key), self.data[key]["name"])

		return min_im

	def add_to_db(self, output, name, face_frames, side_data=None):
		if side_data is None:
			side_data = {}

		new_id = self.get_new_id()
		if os.path.exists(f"faces/{new_id}.jpg"):
			new_id += 1

		cv2.imwrite(f"faces/{new_id}.jpg", Engine.turn_rgb(tf.cast((face_frames * 128.) + 127., tf.uint8))[0].numpy())
		self.data[str(new_id)] = {"name": name, "output": output.tolist(), "face": os.path.join(os.getcwd(), "faces", f"{new_id}.jpg"),
		                          "sex": side_data["sex"], "age": side_data["age"], "eth": side_data["eth"]}

		self.save()

	def reset_database(self):
		self.data = {}
		self.save()

		return bytes(np.array([1], dtype=np.float32))


class Engine:
	@staticmethod
	def turn_rgb(images):
		b, g, r = tf.split(images, 3, axis=-1)
		images = tf.concat([r, g, b], -1)

		return images

	@staticmethod
	def set_face(face):
		face = tf.image.resize(face, (112, 112), method="nearest")

		return (tf.cast(face, tf.float32) - 127.5) / 128.

	def find_who(self, path):
		outputs, face_frames = self.go_for_image_features(path, to_bytes=False)
		match = self.db_manager.find_match_in_db(outputs, th=1.0)

		return bytes(np.array(match[1], dtype=np.float32))

	def update_ASE(self, path, person_id):
		image = self.detector.load_image(path)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)
		image = self.detector.align_image_from_eyes(image, eyes)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)

		face_frames = self.detector.take_faces_from_boxes(image, boxes)
		face_frames = self.turn_rgb([self.set_face(n) for n in face_frames])

		sex = self.ase_predictor.predict_sex(face_frames).tolist()  # {0: "man", 1: "woman"}
		age = self.ase_predictor.predict_age(face_frames).tolist()  # lambda x: f"{int(x*5)-{int(x*5)+5}}"
		eth = self.ase_predictor.predict_ethnicity(face_frames).tolist()  # {0: "white", 1: "black", 2: "asian", 3: "indian", 4: "Others"}
		side_data = {"sex": sex, "age": age, "eth": eth}

		try:
			self.db_manager.data[str(person_id)]["sex"] = side_data["sex"]
			self.db_manager.data[str(person_id)]["age"] = side_data["age"]
			self.db_manager.data[str(person_id)]["eth"] = side_data["eth"]

			self.db_manager.save()
		except KeyError:
			return bytes(np.array([-1], dtype=np.float32))

		return bytes(np.array([1], dtype=np.float32))

	def add_to_database(self, path, name):
		outputs, face_frames = self.go_for_image_features(path, to_bytes=False)
		outputs = outputs.reshape(-1, 512)
		sex = self.ase_predictor.predict_sex(face_frames).tolist()  # {0: "man", 1: "woman"}
		age = self.ase_predictor.predict_age(face_frames).tolist()  # lambda x: f"{int(x*5)-{int(x*5)+5}}"
		eth = self.ase_predictor.predict_ethnicity(face_frames).tolist()  # {0: "white", 1: "black", 2: "asian", 3: "indian", 4: "Others"}
		side_data = {"sex": sex, "age": age, "eth": eth}

		self.db_manager.add_to_db(outputs, name=name, face_frames=face_frames, side_data=side_data)

		return bytes(np.array([1], dtype=np.float32))

	def is_deepfake(self, path):
		image = self.detector.load_image(path)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)
		image = self.detector.align_image_from_eyes(image, eyes)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)

		face_frames = self.detector.take_faces_from_boxes(image, boxes)
		face_frames = self.turn_rgb([self.set_face(n) for n in face_frames])

		return bytes(np.array(tf.cast(tf.multiply(self.df_predictor.predict_deepfake(face_frames), 100), tf.int32).numpy(), dtype=np.float32))

	def get_only_face_and_save(self, path):
		image = self.detector.load_image(path)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)
		image = self.detector.align_image_from_eyes(image, eyes)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)

		face_frames = self.detector.take_faces_from_boxes(image, boxes)
		face_frames = self.turn_rgb([self.set_face(n) for n in face_frames])

		face_id = self.utils.get_faces2display_id()
		cv2.imwrite(f"faces2display/{face_id}.jpg", Engine.turn_rgb(tf.cast((face_frames * 128.) + 127., tf.uint8))[0].numpy())

		return bytes(np.array([face_id], dtype=np.float32))

	def __init__(self, model_path: str):
		self.cos_dis = tf.keras.losses.CosineSimilarity()
		self.ase_predictor = ASE_FP.Tester(
			"../../age_sex_ethnicity_detection/models_all/sex_model.h5",
			"../../age_sex_ethnicity_detection/models_all/age_model.h5",
			"../../age_sex_ethnicity_detection/models_all/eth_model.h5",
		)
		self.df_predictor = DF_FP.Tester(
			"../../deepfake_detection/models_all/deepfake_model.h5"
		)

		self.utils = Utils()
		self.db_manager = DataBaseManager(self.cos_dis)

		self.model = tf.keras.models.load_model(model_path)
		self.data = {}
		self.detector = mtcnn_detector.Engine()

		self.find_who("init.jpg")
		self.db_manager.get_2d_space()

	@staticmethod
	def flip_batch(batch):
		return batch[:, :, ::-1, :]

	def get_output(self, images):
		return tf.nn.l2_normalize(self.model(images, training=False)) +\
		       tf.nn.l2_normalize(self.model(self.flip_batch(images), training=False))

	def go_full_webcam(self, path=0):
		try:
			path = int(path)
		except:
			pass

		cap = cv2.VideoCapture(path)

		if not cap.isOpened():
			print("No webcam!")
			return bytes(np.array([0], dtype=np.float32))

		color_map = {}
		video_writer = None

		while True:
			try:
				ret, frame = cap.read()

				if not ret:
					break

				if video_writer is None:
					h, w, _ = frame.shape
					video_writer = cv2.VideoWriter('output.avi', cv2.VideoWriter_fourcc(*'XVID'), 16.0, (w, h))

				image = frame.copy()
				faces = self.detector.get_faces_from_image(image)
				boxes1, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)
				if len(boxes1) > 0:
					image = self.detector.align_image_from_eyes(image, eyes)
					faces = self.detector.get_faces_from_image(image)
					boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)

					face_frames = self.detector.take_faces_from_boxes(image, boxes)
					face_frames = self.turn_rgb([self.set_face(n) for n in face_frames])

					output = self.get_output(face_frames).numpy()

					colors = []
					names = [self.db_manager.find_match_in_db(out, th=1.0)[-1] for out in output]
					for name in names:
						if not name in color_map.keys():
							color_map[name] = self.detector.generate_color()

						colors.append(color_map[name])

					frame = self.detector.draw_faces_and_labels_on_image(frame, boxes1, names, color=colors)
					video_writer.write(frame)

				cv2.imshow('Input', frame)

				c = cv2.waitKey(1)
				if c == 27 or ret is False:
					video_writer.release()
					break

			except Exception as err:
				print(err)
				if "not valid" in str(err):
					video_writer.release()
					break
				continue

		cap.release()
		cv2.destroyAllWindows()
		video_writer.release()

		return bytes(np.array([1], dtype=np.float32))

	def go_for_image_features(self, path, to_bytes: bool = True):
		print(f"Getting Features for: {path}")
		image = self.detector.load_image(path)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)
		image = self.detector.align_image_from_eyes(image, eyes)
		faces = self.detector.get_faces_from_image(image)
		boxes, eyes = self.detector.get_boxes_from_faces_with_eyes(faces)

		face_frames = self.detector.take_faces_from_boxes(image, boxes)
		face_frames = self.turn_rgb([self.set_face(n) for n in face_frames])

		output = self.get_output(face_frames)[0].numpy()

		if to_bytes:
			output = output.tobytes()

			return output

		else:
			return output, face_frames

	def compare_two(self, path1, path2, to_bytes: bool = True):
		output1, face_frames1 = self.go_for_image_features(path1, to_bytes=False)
		output2, face_frames2 = self.go_for_image_features(path2, to_bytes=False)
		dist = self.cos_dis(output1, output2).numpy()
		print(f"Distance between {path1} - {path2} --> {dist}")

		if to_bytes:
			dist = tf.cast([dist], tf.float32).numpy().tostring()

		return dist

	def save_outputs_to_json(self, path):
		outputs, face_frames = self.go_for_image_features(path, to_bytes=False)
		file_id = self.utils.save_outputs(path, outputs)

		return bytes(np.array([file_id], dtype=np.float32))


if __name__ == '__main__':
	e = Engine("arcface_final.h5")
	print(e.go_full_webcam("vv_elon.gif"))
	# e.go_full_webcam()
