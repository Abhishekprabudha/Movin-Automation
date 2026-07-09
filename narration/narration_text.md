Hello Everyone, lets begin.

This is a demonstration of the Unifleet app.

For this demo, we have selected three live delivery IDs, also called shipment IDs. Each shipment has a different status, so we can clearly see how the Unifleet agent identifies the shipment, reads the available information, and shows the latest status.

We will look at two views.

The first view is for the customer, or end user. The second view is for the operations team. Both views use the same shipment data, but the information is presented differently. The customer view is simple and easy to understand. The operations view includes more detailed information, so the team can take action when needed.

Let us start with the first shipment, which has already been delivered.

In the customer view, I enter the shipment ID and click Track. The app shows that the shipment was delivered on July 6. It also shows the key stages the shipment passed through before delivery.

Now let us check the same shipment in the operations view. Here, we see the same basic shipment status, along with additional operational details, including the committed dates and delivery milestones. This helps the operations team understand not only what happened, but also whether the shipment followed the expected plan.

Next, let us look at the second shipment. This shipment is currently at the sorting hub.

In the customer view, once I enter the shipment ID and click Track, the app shows that the shipment is on track and currently at the sorting hub. It also shows the current location. The customer can also click View on Map to see the route visually.

Because this is an in-transit shipment, the map shows the expected movement path. It gives the customer a simple way to understand where the shipment is and how it is moving.

For this shipment, the app also shows an option to create an appointment. The Unifleet agent reads the available shipment communication and identifies that this shipment does not yet have an appointment. The customer can choose a preferred date and time, add delivery instructions, and provide a phone number for a call before delivery. For example, the customer may request: please call me 30 minutes before delivery.

After the customer submits the appointment request, it is created in the backend. The operations team can then view and act on it through the tracker.

Now let us open the same shipment in the operations view. The operations team can see that the shipment is on the planned path. They can also view the estimated time of arrival. In the customer view, the app keeps the message simple and shows the expected delivery status. In the operations view, the app gives more detail, including when the shipment was committed and when it is likely to be delivered. This gives the team confidence that the shipment is still on track.

Now let us look at the third shipment, which has a shelved status.

In the customer view, the app clearly tells the customer to contact the customer experience team. It also provides the option to create a new appointment, if required.

In the operations view, the team can see more context. The app indicates that an incident is affecting the estimated delivery time. This helps the team understand the reason for the delay and take the next required action.

Apart from tracking individual shipments, Unifleet also supports prediction from file. This works like a bulk upload feature.

For example, I can upload the shipment dump for July 6. The Unifleet agent reads the uploaded file and makes the records available in the app. I can then select any shipment from the uploaded data and check its current status. This is useful for reviewing many shipments together, including current shipments and historical shipment data.

The app can also show cancelled or incomplete shipments correctly. For example, if a pickup was not completed because the shipment was cancelled, the tracker shows that status clearly. This makes bulk review easier for the operations team.

Next, let us look at the simulate and predict feature.

This feature allows the operations team to test different shipment scenarios. For example, we can set the pickup date as today, choose an origin such as Bangalore, add intermediate locations such as Ahmedabad and Kolkata, and then set the final destination as Guwahati.

As we build the route, the app updates the locations dynamically. We can also add exceptions at specific locations. For example, we can add an uncontrollable situation at Ahmedabad, and another exception at Guwahati.

The app then predicts the expected delivery date in real time. This helps the operations team understand the possible risk in a route before or during execution. It also helps them decide what communication or action may be needed if an exception occurs.

This simulation is based on model training using historical shipment data. The model has been trained on around 13,000 shipments and more than 2,700 lanes. Because of this training, the app can estimate the impact of route choices, exceptions, and delays.

For demo purposes, the app also includes predefined sample data. If live data is not available, we can open the in-transit dashboard and use the dummy dataset to explore the tool. This helps anyone quickly understand the capability of the app.

Finally, the network map shows the path each shipment is taking. It gives a visual view of the shipment journey and helps both customers and operations teams understand movement more clearly.

In summary, Unifleet provides live shipment tracking, customer-friendly status updates, operations-level visibility, appointment creation, bulk upload, route simulation, delivery prediction, and network mapping.

Thank you.
