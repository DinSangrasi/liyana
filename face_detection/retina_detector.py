import cv2
import numpy as np

import insightface
from face_detection.detector_main import MainHelper


class Engine(MainHelper):
    def draw_faces_and_labels_on_image(self, image, boxes, labels, color=(255, 0, 0), thickness: int = 5):
        if type(color) is not list:
            cl = color
            color = [cl for _ in range(len(boxes))]

        for box, clr, label in zip(boxes, color, labels):
            x1, y1, x2, y2 = box
            color2g = clr
            if clr == "different":
                color2g = self.generate_color()

            cv2.rectangle(image, (x1, y1), (x2, y2), color2g, thickness)
            cv2.putText(image, label, (x1, y1 - 5), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, color2g, 2, cv2.LINE_AA)

        return image

    def draw_faces_on_image(self, image, boxes, color=(255, 0, 0), thickness: int = 5):
        if type(color) is not list:
            cl = color
            color = [cl for _ in range(len(boxes))]

        for box, clr in zip(boxes, color):
            x1, y1, x2, y2 = box
            color2g = clr
            if clr == "different":
                color2g = self.generate_color()

            cv2.rectangle(image, (x1, y1), (x2, y2), color2g, thickness)

        return image

    def __init__(self, **kwargs):
        super(Engine, self).__init__(**kwargs)

        self.net = insightface.model_zoo.get_model('retinaface_r50_v1')
        self.net.prepare(ctx_id=0, nms=0.6)

        self.scale = 1/2

    def get_faces_from_image(self, image):
        image = cv2.resize(image, None, fx=self.scale, fy=self.scale)

        faces, _ = self.net.detect(image, scale=1.0)

        return faces

    def take_faces_from_boxes(self, image, boxes):
        frames = []
        for box in boxes:
            x1, y1, x2, y2 = box
            diff = int(112/abs((y2-y1) - (x2-x1)))*2

            if y2 > x2:
                x_e, y_e = 2*diff, diff
            elif y2 == x2:
                x_e, y_e = 0, 0
            else:
                x_e, y_e = diff, 2*diff

            frames.append(image[y1-y_e:y2+y_e, x1-x_e:x2+x_e])

        return frames       

    def get_boxes_from_faces(self, faces, th: float = 0.9):
        boxes = []
        for i in range(len(faces)):
            if faces[i][-1] > th:
                bbox_ltrb = faces[i][:4] * (1/self.scale)
                conf = faces[i][-1]
                boxes.append(bbox_ltrb.astype(np.int))

        return boxes


if __name__ == '__main__':
    e = Engine()

    image = e.load_image("test.jpg")

    faces = e.get_faces_from_image(image)
    boxes = e.get_boxes_from_faces(faces)
    image = e.draw_faces_on_image(image, boxes, color="different")

    e.display_image(image, destroy_after=False, n=0)
